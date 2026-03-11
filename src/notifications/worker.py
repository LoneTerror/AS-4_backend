# src/notifications/worker.py
"""
Background Email + Slack Worker
════════════════════════════════
Architecture change: DB polling → Redis queue (BLPOP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

# --- OpenTelemetry Import ---
from opentelemetry import trace
# ----------------------------

if TYPE_CHECKING:
    from prisma import Prisma
    from .email_sender import EmailSender
    from .slack_sender import SlackSender

import redis.asyncio as aioredis

from .cache import (
    QUEUE_KEY,
    dequeue_notification,
    get_cached_employee,
    set_cached_employee,
    get_cached_celebration_employees,
    set_cached_celebration_employees,
    get_cached_slack_uid,
    set_cached_slack_uid,
    enqueue_notification,
)

logger = logging.getLogger(__name__)

# Initialize the tracer for this background worker
tracer = trace.get_tracer(__name__)

CELEBRATION_CHECK_INTERVAL_SECONDS: int = 3600

# ── Startup recovery ──────────────────────────────────────────────────────────

async def _recover_pending(db: "Prisma", r: aioredis.Redis) -> int:
    """
    On startup, find any notifications that were created before this process
    started and never got email_sent=True. Push their IDs into the Redis queue.
    Runs once — prevents dropped notifications across restarts.
    """
    # Trace the recovery process
    with tracer.start_as_current_span("worker_startup_recovery") as span:
        startup_cutoff = datetime.now(tz=timezone.utc)
        pending = await db.notifications.find_many(
            where={
                "email_sent": False,
                "type": {"not": "CELEBRATION"},
                "created_at": {"lt": startup_cutoff},
            },
            order={"created_at": "asc"},
        )
        span.set_attribute("recovery.pending_count", len(pending))
        
        if pending:
            pipe = r.pipeline()
            for n in pending:
                pipe.lpush(QUEUE_KEY, str(n.notification_id))
            await pipe.execute()
            logger.info("Worker recovery: re-queued %d pending notification(s)", len(pending))
        return len(pending)


# ── Regular notification worker ───────────────────────────────────────────────

async def _get_employee(db: "Prisma", r: aioredis.Redis, employee_id: str) -> dict | None:
    """Fetch employee with Redis cache. Falls back to DB on cache miss."""
    cached = await get_cached_employee(r, employee_id)
    if cached:
        return cached

    emp = await db.employees.find_unique(where={"employee_id": employee_id})
    if emp is None:
        return None

    emp_dict = {"employee_id": str(emp.employee_id), "email": emp.email, "username": emp.username}
    await set_cached_employee(r, employee_id, emp_dict)
    return emp_dict


async def _get_slack_uid(
    slack: "SlackSender | None",
    r: aioredis.Redis,
    email: str,
) -> str | None:
    """Slack UID lookup with 24h Redis cache. Returns None if Slack disabled."""
    if not slack:
        return None

    cached = await get_cached_slack_uid(r, email)
    if cached is not None:
        # "" means we cached a "not found" — skip the API call
        return cached if cached else None

    uid = await slack.get_user_id_by_email(email)
    await set_cached_slack_uid(r, email, uid)
    return uid


async def _process_one(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None",
    r: aioredis.Redis,
    notification_id: str,
) -> bool:
    from .email_sender import build_notification_html

    # --- START CUSTOM TRACE SPAN ---
    with tracer.start_as_current_span("process_single_notification") as span:
        span.set_attribute("notification.id", notification_id)

        notification = await db.notifications.find_unique(
            where={"notification_id": notification_id}
        )
        if notification is None:
            span.set_attribute("notification.status", "not_found_in_db")
            logger.warning("Worker: notification %s not found in DB — skipping", notification_id)
            return False

        if notification.email_sent:
            span.set_attribute("notification.status", "already_sent")
            logger.debug("Worker: notification %s already sent — skipping duplicate", notification_id)
            return True
            
        span.set_attribute("notification.type", notification.type)

        employee = await _get_employee(db, r, str(notification.employee_id))
        if employee is None:
            span.set_attribute("notification.status", "employee_not_found")
            logger.warning(
                "Worker: employee %s not found — marking sent to avoid retry loop",
                notification.employee_id,
            )
            await _mark_email_sent(db, notification_id)
            return False

        try:
            html = build_notification_html(
                title=notification.title,
                message=notification.message,
                type_=notification.type,
            )

            async def _email_coro() -> None:
                # Add an inner span just for the SMTP call
                with tracer.start_as_current_span("send_smtp_email"):
                    await sender.send_notification_email(
                        to_email=employee["email"],
                        subject=notification.title,
                        body_html=html,
                    )

            async def _slack_coro() -> None:
                try:
                    uid = await _get_slack_uid(slack, r, employee["email"])
                    if uid:
                        # Add an inner span just for the Slack API call
                        with tracer.start_as_current_span("send_slack_dm"):
                            await slack.send_dm(
                                slack_user_id=uid,
                                title=notification.title,
                                message=notification.message,
                                type_=notification.type,
                            )
                except Exception:
                    logger.warning(
                        "Worker: Slack DM failed for notification %s — email still sent",
                        notification_id,
                    )

            await asyncio.gather(_email_coro(), _slack_coro())
            await _mark_email_sent(db, notification_id)
            span.set_attribute("notification.status", "success")
            return True

        except Exception as e:
            span.record_exception(e) # Attaches the error stack trace to Jaeger
            span.set_attribute("notification.status", "failed")
            logger.exception("Worker: failed to send notification %s", notification_id)
            return False


async def _mark_email_sent(db: "Prisma", notification_id: str) -> None:
    await db.notifications.update(
        where={"notification_id": notification_id},
        data={"email_sent": True},
    )


async def email_worker_loop(
    db: "Prisma",
    sender: "EmailSender",
    r: aioredis.Redis,
    slack: "SlackSender | None" = None,
) -> None:
    """
    Main worker loop.
    1. On startup: recover any notifications missed while the process was down.
    2. Then: BLPOP — blocks until a notification_id arrives in the queue.
       No DB queries at all when the queue is empty.
    """
    recovered = await _recover_pending(db, r)
    logger.info(
        "Email worker started — BLPOP mode (recovered=%d, queue=%s)",
        recovered,
        QUEUE_KEY,
    )

    while True:
        try:
            notification_id = await dequeue_notification(r, timeout=5)
            if notification_id is None:
                # Timeout — loop back and block again. No DB hit.
                continue

            success = await _process_one(db, sender, slack, r, notification_id)
            if success:
                logger.info("Worker: sent notification %s", notification_id)

        except asyncio.CancelledError:
            logger.info("Email worker shutting down.")
            raise
        except Exception:
            logger.exception("Email worker: unexpected error")
            await asyncio.sleep(2)   # brief back-off on unexpected errors


# ── Celebration worker ────────────────────────────────────────────────────────

async def celebration_worker_loop(
    db: "Prisma",
    sender: "EmailSender",
    r: aioredis.Redis,
    slack: "SlackSender | None" = None,
) -> None:
    logger.info(
        "Celebration worker started — checking every %ds",
        CELEBRATION_CHECK_INTERVAL_SECONDS,
    )
    while True:
        try:
            await _process_celebrations(db, sender, r, slack)
        except asyncio.CancelledError:
            logger.info("Celebration worker shutting down.")
            raise
        except Exception:
            logger.exception("Celebration worker: unexpected error")

        await asyncio.sleep(CELEBRATION_CHECK_INTERVAL_SECONDS)


async def _get_all_active_employees_cached(db: "Prisma", r: aioredis.Redis) -> list:
    """
    Returns all active employees for the celebration broadcast.
    Cached for 1h — the celebration worker only runs hourly anyway.
    Cache stores minimal fields needed for email sending.
    """
    with tracer.start_as_current_span("fetch_active_employees_for_broadcast"):
        cached = await get_cached_celebration_employees(r)
        if cached is not None:
            logger.debug("Celebration worker: active employees from cache (%d)", len(cached))
            return cached

        all_employees_raw = await db.employees.find_many(
            include={"status_master_employees_status_idTostatus_master": True}
        )
        active = [
            {
                "employee_id": str(e.employee_id),
                "email": e.email,
                "username": e.username,
            }
            for e in all_employees_raw
            if (
                e.status_master_employees_status_idTostatus_master is not None
                and e.status_master_employees_status_idTostatus_master.status_code == "ACTIVE"
            )
        ]
        await set_cached_celebration_employees(r, active)
        logger.debug("Celebration worker: loaded %d active employees from DB → cached", len(active))
        return active


async def _process_celebrations(
    db: "Prisma",
    sender: "EmailSender",
    r: aioredis.Redis,
    slack: "SlackSender | None" = None,
) -> None:
    from .email_sender import build_celebration_html
    from .service import NotificationService
    from .schemas import NotificationType

    # Wrap the hourly check in a span
    with tracer.start_as_current_span("check_daily_celebrations") as main_span:

        svc = NotificationService(db)
        celebrants = await svc.get_employees_with_celebrations_today()
        
        main_span.set_attribute("celebrants.count", len(celebrants))

        if not celebrants:
            logger.debug("Celebration worker: no celebrations today.")
            return

        # Use cached active employee list — avoids SELECT * FROM employees every hour
        all_active_employees = await _get_all_active_employees_cached(db, r)

        if not all_active_employees:
            logger.warning("Celebration worker: no active employees found.")
            return

        for person in celebrants:
            # Trace the broadcast process for EACH celebrant
            with tracer.start_as_current_span("broadcast_celebration") as person_span:
                person_span.set_attribute("celebrant.name", person["username"])
                person_span.set_attribute("celebration.type", person["celebration_type"])

                try:
                    already_sent = await svc.celebration_already_sent_today(
                        employee_id=person["employee_id"],
                        celebration_type=person["celebration_type"],
                    )
                    if already_sent:
                        person_span.set_attribute("celebration.status", "already_sent")
                        logger.debug(
                            "Celebration worker: sentinel found for %s %s — skipping.",
                            person["celebration_type"],
                            person["username"],
                        )
                        continue

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

                    async def _notify_recipient(recipient: dict) -> bool:
                        is_celebrant = recipient["employee_id"] == str(person["employee_id"])
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
                                employee_id=recipient["employee_id"],
                                title=subject_to_send,
                                message=plain_to_send,
                                type=NotificationType.CELEBRATION,
                            )
                            await sender.send_notification_email(
                                to_email=recipient["email"],
                                subject=subject_to_send,
                                body_html=html_to_send,
                            )
                            await _mark_email_sent(db, str(notification["notification_id"]))
                            return True
                        except Exception:
                            logger.exception(
                                "Celebration worker: failed to notify %s about %s's %s",
                                recipient["employee_id"],
                                person["username"],
                                person["celebration_type"],
                            )
                            return False

                    results = await asyncio.gather(
                        _slack_broadcast(),
                        *[_notify_recipient(r_emp) for r_emp in all_active_employees],
                    )

                    broadcast_count = sum(res for res in results[1:] if res)
                    person_span.set_attribute("celebration.status", "success")
                    person_span.set_attribute("celebration.broadcast_count", broadcast_count)
                    
                    logger.info(
                        "Celebration worker: %s for %s → %d/%d employees notified",
                        person["celebration_type"],
                        person["username"],
                        broadcast_count,
                        len(all_active_employees),
                    )

                except Exception as e:
                    person_span.record_exception(e)
                    person_span.set_attribute("celebration.status", "failed")
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