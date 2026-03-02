"""
Background Email Worker
═══════════════════════
Runs as a plain asyncio Task inside the FastAPI process.

Design decisions
────────────────
• No broker (Kafka / Redis / RabbitMQ) — not needed at this scale.
• Batch size 20 per tick — avoids memory spikes and long DB locks.
• All failures are caught and logged; the worker NEVER crashes the server.
• The task is cancelled cleanly during lifespan shutdown.

Fix notes
─────────
• Regular email worker excludes type="CELEBRATION" rows — those are fully
  handled (send + mark email_sent) by the celebration worker.
• On startup, any notification that was already sitting unsent in the DB is
  skipped by recording the startup timestamp and only processing rows created
  AFTER that moment (STARTUP_CUTOFF). Change SKIP_EMAILS_BEFORE_STARTUP to
  False if you ever want the old behaviour back.
• Celebration emails are broadcast to ALL active employees. Each recipient
  gets their own notification row so read/unread state is tracked per-person.
• Idempotency uses a SENTINEL row written to the celebrant BEFORE the
  broadcast loop. This means a mid-loop server restart won't re-start the
  broadcast from scratch — the sentinel is found and the whole event is
  skipped cleanly.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prisma import Prisma
    from .email_sender import EmailSender

logger = logging.getLogger(__name__)

# ── Tuneable constants (easy to change) ────────────────────────────────────────

POLL_INTERVAL_SECONDS: int = 10                 # how often the email worker wakes up
BATCH_SIZE: int = 20                            # max notifications processed per tick
CELEBRATION_CHECK_INTERVAL_SECONDS: int = 3600  # celebration worker cadence (1 hr)

# Set to True  → skip any email_sent=False rows that already existed when the
#                server started (safe default — avoids re-sending stale emails).
# Set to False → send everything in the DB regardless of age (original behaviour).
SKIP_EMAILS_BEFORE_STARTUP: bool = True

# Populated once at import time; used as the cutoff for the email worker.
STARTUP_CUTOFF: datetime = datetime.now(tz=timezone.utc)


# ── Core loop ──────────────────────────────────────────────────────────────────

async def _process_batch(db: "Prisma", sender: "EmailSender") -> int:
    """
    Single processing tick.

    Selects up to BATCH_SIZE unsent, non-celebration notifications that were
    created after STARTUP_CUTOFF (when SKIP_EMAILS_BEFORE_STARTUP is True),
    sends each one, then marks it email_sent=True.
    """
    from .email_sender import build_notification_html

    where: dict = {
        "email_sent": False,
        # Celebrations are fully handled by celebration_worker_loop
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

    sent_count = 0
    for notification in pending:
        try:
            employee = await db.employees.find_unique(
                where={"employee_id": notification.employee_id},
                include={"status_master_employees_status_idTostatus_master": False},
            )
            if employee is None:
                logger.warning(
                    "Worker: employee %s not found — skipping notification %s",
                    notification.employee_id,
                    notification.notification_id,
                )
                await _mark_email_sent(db, str(notification.notification_id))
                continue

            html = build_notification_html(
                title=notification.title,
                message=notification.message,
                type_=notification.type,
            )
            await sender.send_notification_email(
                to_email=employee.email,
                subject=notification.title,
                body_html=html,
            )
            await _mark_email_sent(db, str(notification.notification_id))
            sent_count += 1

        except Exception:
            logger.exception(
                "Worker: failed to send email for notification %s",
                notification.notification_id,
            )

    return sent_count


async def _mark_email_sent(db: "Prisma", notification_id: str) -> None:
    await db.notifications.update(
        where={"notification_id": notification_id},
        data={"email_sent": True},
    )


# ── Worker task ────────────────────────────────────────────────────────────────

async def email_worker_loop(db: "Prisma", sender: "EmailSender") -> None:
    logger.info(
        "Email worker started (cutoff=%s) — polling every %ds, batch=%d, skip_old=%s",
        STARTUP_CUTOFF.isoformat(),
        POLL_INTERVAL_SECONDS,
        BATCH_SIZE,
        SKIP_EMAILS_BEFORE_STARTUP,
    )
    while True:
        try:
            sent = await _process_batch(db, sender)
            if sent:
                logger.info("Email worker: sent %d notification(s) this tick", sent)
        except asyncio.CancelledError:
            logger.info("Email worker shutting down.")
            raise
        except Exception:
            logger.exception("Email worker: unexpected error in processing loop")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


# ── Celebration worker ─────────────────────────────────────────────────────────

async def celebration_worker_loop(db: "Prisma", sender: "EmailSender") -> None:
    """
    Runs once per hour.

    For each employee whose birthday or work anniversary is today:
      1. Writes a SENTINEL notification row for the celebrant first.
      2. Broadcasts a notification + email to ALL active employees.
      3. Idempotency guard on the sentinel prevents re-sending on restart.
    """
    logger.info(
        "Celebration worker started — checking every %ds",
        CELEBRATION_CHECK_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _process_celebrations(db, sender)
        except asyncio.CancelledError:
            logger.info("Celebration worker shutting down.")
            raise
        except Exception:
            logger.exception("Celebration worker: unexpected error")

        await asyncio.sleep(CELEBRATION_CHECK_INTERVAL_SECONDS)


async def _process_celebrations(db: "Prisma", sender: "EmailSender") -> None:
    from .email_sender import build_celebration_html
    from .service import NotificationService
    from .schemas import NotificationType

    svc = NotificationService(db)
    celebrants = await svc.get_employees_with_celebrations_today()

    if not celebrants:
        logger.debug("Celebration worker: no celebrations today.")
        return

    # Fetch all active employees once — they are the broadcast recipients
    all_active_employees = await db.employees.find_many(
        where={
            "status_master_employees_status_idTostatus_master": {
                "is": {"status_code": "ACTIVE"}
            }
        },
    )

    if not all_active_employees:
        logger.warning("Celebration worker: no active employees found to notify.")
        return

    for person in celebrants:
        try:
            # ── Idempotency guard ───────────────────────────────────────────
            # Check for the sentinel row that is written BEFORE the broadcast
            # loop. Using the celebrant's own employee_id as anchor is reliable
            # because the sentinel is always the very first thing we write —
            # so if it exists, the entire broadcast either completed or is
            # in-flight from another instance.
            already_sent = await svc.celebration_already_sent_today(
                employee_id=person["employee_id"],
                celebration_type=person["celebration_type"],
            )
            if already_sent:
                logger.debug(
                    "Celebration worker: sentinel found for %s employee %s — skipping.",
                    person["celebration_type"],
                    person["employee_id"],
                )
                continue

            # ── Build email content ─────────────────────────────────────────
            subject, html = build_celebration_html(
                employee_name=person["username"],
                celebration_type=person["celebration_type"],
                years=person.get("years"),
            )
            plain_message = _celebration_plain_message(person)

            # ── Write sentinel FIRST ────────────────────────────────────────
            # This is the celebrant's own notification row. It doubles as the
            # idempotency key: if the server restarts mid-broadcast, the next
            # run finds this sentinel and skips the whole event cleanly.
            sentinel = await svc.create_notification(
                employee_id=person["employee_id"],
                title=subject,
                message=plain_message,
                type=NotificationType.CELEBRATION,
            )
            # Send + mark the sentinel row email_sent immediately
            try:
                await sender.send_notification_email(
                    to_email=person["email"],
                    subject=subject,
                    body_html=html,
                )
                await _mark_email_sent(db, str(sentinel["notification_id"]))
            except Exception:
                logger.exception(
                    "Celebration worker: failed to email celebrant %s",
                    person["employee_id"],
                )
                # Don't mark email_sent=True — the sentinel row still acts as
                # the idempotency key even if the celebrant's own email failed.

            # ── Broadcast to everyone else ──────────────────────────────────
            broadcast_count = 1  # celebrant already counted above
            for recipient in all_active_employees:
                # Skip the celebrant — they already got their row above
                if str(recipient.employee_id) == str(person["employee_id"]):
                    continue
                try:
                    notification = await svc.create_notification(
                        employee_id=recipient.employee_id,
                        title=subject,
                        message=plain_message,
                        type=NotificationType.CELEBRATION,
                    )
                    await sender.send_notification_email(
                        to_email=recipient.email,
                        subject=subject,
                        body_html=html,
                    )
                    await _mark_email_sent(db, str(notification["notification_id"]))
                    broadcast_count += 1

                except Exception:
                    logger.exception(
                        "Celebration worker: failed to notify recipient %s "
                        "about %s's %s",
                        recipient.employee_id,
                        person["username"],
                        person["celebration_type"],
                    )

            logger.info(
                "Celebration worker: broadcast %s for %s to %d/%d employees",
                person["celebration_type"],
                person["username"],
                broadcast_count,
                len(all_active_employees),
            )

        except Exception:
            logger.exception(
                "Celebration worker: failed to process celebration for employee %s",
                person.get("employee_id"),
            )


def _celebration_plain_message(person: dict) -> str:
    """
    Plain-text notification message.

    The raw celebration_type value ("BIRTHDAY" / "WORK_ANNIVERSARY") is
    embedded verbatim inside brackets so that `celebration_already_sent_today`
    can use {"message": {"contains": celebration_type}} as a reliable
    idempotency key.
    """
    name = person["username"]
    if person["celebration_type"] == "BIRTHDAY":
        return f"[BIRTHDAY] Today is {name}'s birthday! Wish them a great day 🎂"
    years = person.get("years")
    return (
        f"[WORK_ANNIVERSARY] {name} is celebrating their {years}-year "
        f"work anniversary today! 🏆"
    )