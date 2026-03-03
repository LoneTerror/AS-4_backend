"""
Background Email + Slack Worker
════════════════════════════════
Runs as plain asyncio Tasks inside the FastAPI process.
Both email and Slack are sent per notification.
Slack failures never block email delivery.
All sending is concurrent via asyncio.gather — never sequential.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prisma import Prisma
    from .email_sender import EmailSender
    from .slack_sender import SlackSender

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 10
BATCH_SIZE: int = 20
CELEBRATION_CHECK_INTERVAL_SECONDS: int = 3600
SKIP_EMAILS_BEFORE_STARTUP: bool = True
STARTUP_CUTOFF: datetime = datetime.now(tz=timezone.utc)


# ── Regular notification worker (REVIEW / REWARD / SYSTEM) ────────────────────

async def _process_batch(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None" = None,
) -> int:
    from .email_sender import build_notification_html

    where: dict = {
        "email_sent": False,
        "type": {"not": "CELEBRATION"},
    }
    if SKIP_EMAILS_BEFORE_STARTUP:
        where["created_at"] = {"gte": STARTUP_CUTOFF}

    pending = await db.notifications.find_many(
        where=where,
        order={"created_at": "asc"},
        take=BATCH_SIZE,
    )

    if not pending:
        return 0

    # One bulk DB query for all employees in this batch instead of N individual lookups
    employee_ids = list({str(n.employee_id) for n in pending})
    employees_list = await db.employees.find_many(
        where={"employee_id": {"in": employee_ids}}
    )
    employees = {str(e.employee_id): e for e in employees_list}

    async def _handle_one(notification) -> bool:
        employee = employees.get(str(notification.employee_id))
        if employee is None:
            logger.warning(
                "Worker: employee %s not found — skipping notification %s",
                notification.employee_id,
                notification.notification_id,
            )
            await _mark_email_sent(db, str(notification.notification_id))
            return False

        try:
            html = build_notification_html(
                title=notification.title,
                message=notification.message,
                type_=notification.type,
            )

            async def _email_coro() -> None:
                await sender.send_notification_email(
                    to_email=employee.email,
                    subject=notification.title,
                    body_html=html,
                )

            async def _slack_coro() -> None:
                if not slack:
                    return
                try:
                    slack_uid = await slack.get_user_id_by_email(employee.email)
                    if slack_uid:
                        await slack.send_dm(
                            slack_user_id=slack_uid,
                            title=notification.title,
                            message=notification.message,
                            type_=notification.type,
                        )
                    else:
                        logger.debug(
                            "Slack: no user found for %s — skipping DM for notification %s",
                            employee.email,
                            notification.notification_id,
                        )
                except Exception:
                    logger.warning(
                        "Worker: Slack DM failed for notification %s — email still sent",
                        notification.notification_id,
                    )

            # Email and Slack fire at the same time for this notification
            await asyncio.gather(_email_coro(), _slack_coro())
            await _mark_email_sent(db, str(notification.notification_id))
            return True

        except Exception:
            logger.exception(
                "Worker: failed to send notification %s",
                notification.notification_id,
            )
            return False

    # Entire batch fires concurrently — all 20 at the same time
    results = await asyncio.gather(*[_handle_one(n) for n in pending])
    sent = sum(results)
    logger.debug("Worker: batch complete — %d/%d sent", sent, len(pending))
    return sent


async def _mark_email_sent(db: "Prisma", notification_id: str) -> None:
    await db.notifications.update(
        where={"notification_id": notification_id},
        data={"email_sent": True},
    )


async def email_worker_loop(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None" = None,
) -> None:
    logger.info(
        "Email worker started (cutoff=%s) — polling every %ds, batch=%d, skip_old=%s",
        STARTUP_CUTOFF.isoformat(),
        POLL_INTERVAL_SECONDS,
        BATCH_SIZE,
        SKIP_EMAILS_BEFORE_STARTUP,
    )
    while True:
        try:
            sent = await _process_batch(db, sender, slack)
            if sent:
                logger.info("Email worker: sent %d notification(s) this tick", sent)
        except asyncio.CancelledError:
            logger.info("Email worker shutting down.")
            raise
        except Exception:
            logger.exception("Email worker: unexpected error in processing loop")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# ── Celebration worker (BIRTHDAY / WORK_ANNIVERSARY) ──────────────────────────

async def celebration_worker_loop(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None" = None,
) -> None:
    logger.info(
        "Celebration worker started — checking every %ds",
        CELEBRATION_CHECK_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _process_celebrations(db, sender, slack)
        except asyncio.CancelledError:
            logger.info("Celebration worker shutting down.")
            raise
        except Exception:
            logger.exception("Celebration worker: unexpected error")

        await asyncio.sleep(CELEBRATION_CHECK_INTERVAL_SECONDS)


async def _process_celebrations(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None" = None,
) -> None:
    from .email_sender import build_celebration_html
    from .service import NotificationService
    from .schemas import NotificationType

    svc = NotificationService(db)
    celebrants = await svc.get_employees_with_celebrations_today()

    if not celebrants:
        logger.debug("Celebration worker: no celebrations today.")
        return

    all_employees_raw = await db.employees.find_many(
        include={"status_master_employees_status_idTostatus_master": True}
    )
    all_active_employees = [
        emp for emp in all_employees_raw
        if (
            emp.status_master_employees_status_idTostatus_master is not None
            and emp.status_master_employees_status_idTostatus_master.status_code == "ACTIVE"
        )
    ]

    if not all_active_employees:
        logger.warning("Celebration worker: no active employees found.")
        return

    # Process each celebrant sequentially (correct — sentinel must be written
    # and checked before any broadcast starts), but broadcast to ALL recipients
    # concurrently within each celebrant's run.
    for person in celebrants:
        try:
            already_sent = await svc.celebration_already_sent_today(
                employee_id=person["employee_id"],
                celebration_type=person["celebration_type"],
            )
            if already_sent:
                logger.debug(
                    "Celebration worker: sentinel found for %s %s — skipping.",
                    person["celebration_type"],
                    person["username"],
                )
                continue

            # Write sentinel before any work so a crash mid-broadcast
            # doesn't cause a double-send on the next hourly tick
            await svc.create_sentinel(
                employee_id=person["employee_id"],
                celebration_type=person["celebration_type"],
                celebrant_name=person["username"],
            )

            personal_subject, personal_html = build_celebration_html(
                employee_name=person["username"],
                celebration_type=person["celebration_type"],
                years=person.get("years"),
                is_personal=True,
            )
            broadcast_subject, broadcast_html = build_celebration_html(
                employee_name=person["username"],
                celebration_type=person["celebration_type"],
                years=person.get("years"),
                is_personal=False,
            )
            broadcast_plain = _celebration_plain_message(person)

            # Slack: single channel post — fire and don't block the email broadcast
            async def _slack_broadcast() -> None:
                if not slack:
                    return
                try:
                    await slack.send_celebration(
                        channel_id=None,
                        employee_name=person["username"],
                        celebration_type=person["celebration_type"],
                        years=person.get("years"),
                    )
                except Exception:
                    logger.warning(
                        "Celebration worker: Slack broadcast failed for %s",
                        person["username"],
                    )

            # Per-recipient coroutine — create DB row then send email,
            # both steps in one async unit so we can gather across all recipients
            async def _notify_recipient(recipient) -> bool:
                is_celebrant = str(recipient.employee_id) == str(person["employee_id"])

                if is_celebrant:
                    subject_to_send = personal_subject
                    html_to_send    = personal_html
                    plain_to_send   = (
                        f"[{person['celebration_type']}] Happy "
                        f"{person['celebration_type'].replace('_', ' ').title()}, "
                        f"{person['username']}!"
                    )
                else:
                    subject_to_send = broadcast_subject
                    html_to_send    = broadcast_html
                    plain_to_send   = broadcast_plain

                try:
                    notification = await svc.create_notification(
                        employee_id=recipient.employee_id,
                        title=subject_to_send,
                        message=plain_to_send,
                        type=NotificationType.CELEBRATION,
                    )
                    await sender.send_notification_email(
                        to_email=recipient.email,
                        subject=subject_to_send,
                        body_html=html_to_send,
                    )
                    await _mark_email_sent(db, str(notification["notification_id"]))
                    return True
                except Exception:
                    logger.exception(
                        "Celebration worker: failed to notify %s about %s's %s",
                        recipient.employee_id,
                        person["username"],
                        person["celebration_type"],
                    )
                    return False

            # Slack post + all recipient emails fire concurrently
            results = await asyncio.gather(
                _slack_broadcast(),
                *[_notify_recipient(r) for r in all_active_employees],
            )

            # results[0] is the Slack coro (returns None), rest are bools
            broadcast_count = sum(r for r in results[1:] if r)
            logger.info(
                "Celebration worker: %s for %s → %d/%d employees notified",
                person["celebration_type"],
                person["username"],
                broadcast_count,
                len(all_active_employees),
            )

        except Exception:
            logger.exception(
                "Celebration worker: failed to process celebration for %s",
                person.get("employee_id"),
            )


def _celebration_plain_message(person: dict) -> str:
    name = person["username"]
    if person["celebration_type"] == "BIRTHDAY":
        return f"[BIRTHDAY] Today is {name}'s birthday! Wish them a great day."
    years = person.get("years")
    return (
        f"[WORK_ANNIVERSARY] {name} is celebrating their {years}-year "
        f"work anniversary today."
    )