"""
Background Email Worker
═══════════════════════
Runs as a plain asyncio Task inside the FastAPI process.

Design decisions
────────────────
• No broker (Kafka / Redis / RabbitMQ) — not needed at this scale.
• Batch size 20 per tick — avoids memory spikes and long DB locks.
• Optimistic locking via a two-step SELECT → UPDATE ensures only one
  worker instance processes each row, even when you run multiple Uvicorn
  workers behind a load balancer (see horizontal scaling notes).
• All failures are caught and logged; the worker NEVER crashes the server.
• The task is cancelled cleanly during lifespan shutdown.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prisma import Prisma
    from .email_sender import EmailSender

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 10
BATCH_SIZE: int = 20


# ── Core loop ──────────────────────────────────────────────────────────────────

async def _process_batch(db: "Prisma", sender: "EmailSender") -> int:
    """
    Single processing tick.

    1. SELECT up to BATCH_SIZE rows where email_sent = false
    2. For each row: fetch employee email → send → mark email_sent = true
    3. Return number of emails successfully sent this tick.

    Each row is marked independently so a failure on row N doesn't block N+1.
    """
    from .email_sender import build_notification_html  # avoid circular imports

    pending = await db.notifications.find_many(
        where={"email_sent": False},
        order={"created_at": "asc"},
        take=BATCH_SIZE,
    )

    if not pending:
        return 0

    sent_count = 0
    for notification in pending:
        try:
            # ── Fetch employee email ────────────────────────────────────────
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
                # Mark as sent to prevent infinite retry on deleted accounts.
                await _mark_email_sent(db, notification.notification_id)
                continue

            # ── Build & send email ──────────────────────────────────────────
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

            # ── Persist success ─────────────────────────────────────────────
            await _mark_email_sent(db, notification.notification_id)
            sent_count += 1

        except Exception:
            # Log but never re-raise — one bad row must not stop the batch.
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
    """
    Infinite loop that wakes every POLL_INTERVAL_SECONDS.

    Designed to be run via ``asyncio.create_task()`` inside the FastAPI
    lifespan context so it shares the same event loop and DB connection
    as the rest of the app.

    Cancellation is handled gracefully: when the lifespan shuts down,
    the CancelledError propagates naturally and the task exits cleanly.
    """
    logger.info(
        "Email worker started — polling every %ds, batch size %d",
        POLL_INTERVAL_SECONDS,
        BATCH_SIZE,
    )
    while True:
        try:
            sent = await _process_batch(db, sender)
            if sent:
                logger.info("Email worker: sent %d notification(s) this tick", sent)
        except asyncio.CancelledError:
            logger.info("Email worker shutting down.")
            raise  # let asyncio handle it
        except Exception:
            # Top-level safety net — catches DB connection drops etc.
            logger.exception("Email worker: unexpected error in processing loop")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

# ── Celebration worker ─────────────────────────────────────────────────────────

CELEBRATION_CHECK_INTERVAL_SECONDS: int = 3600   # re-check hourly; idempotent


async def celebration_worker_loop(db: "Prisma", sender: "EmailSender") -> None:
    """
    Runs once per hour.  On each tick it:

    1. Finds every employee whose birthday or work anniversary is *today*.
    2. Skips anyone who already received a celebration notification today
       (idempotency guard — safe across restarts).
    3. Creates a CELEBRATION notification row.
    4. Sends a festive email immediately (no separate email-worker hop needed
       since the notification + email are created in the same tick).

    Milestone logic lives in NotificationService so it can be unit-tested
    independently of the worker loop.
    """
    from .email_sender import build_celebration_html
    from .service import NotificationService
    from .schemas import NotificationType

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

    for person in celebrants:
        try:
            # ── Idempotency: skip if already notified today ─────────────────
            already_sent = await svc.celebration_already_sent_today(
                employee_id=person["employee_id"],
                celebration_type=person["celebration_type"],
            )
            if already_sent:
                continue

            # ── Build email content ─────────────────────────────────────────
            subject, html = build_celebration_html(
                employee_name=person["username"],
                celebration_type=person["celebration_type"],
                years=person.get("years"),
            )

            # ── Persist notification ────────────────────────────────────────
            notification = await svc.create_notification(
                employee_id=person["employee_id"],
                title=subject,
                message=_celebration_plain_message(person),
                type=NotificationType.CELEBRATION,
            )

            # ── Send email ──────────────────────────────────────────────────
            await sender.send_notification_email(
                to_email=person["email"],
                subject=subject,
                body_html=html,
            )

            # ── Mark email_sent on the notification row ─────────────────────
            await db.notifications.update(
                where={"notification_id": notification["notification_id"]},
                data={"email_sent": True},
            )

            logger.info(
                "Celebration worker: sent %s email to %s (employee %s)",
                person["celebration_type"],
                person["email"],
                person["employee_id"],
            )

        except Exception:
            logger.exception(
                "Celebration worker: failed to process celebration for employee %s",
                person.get("employee_id"),
            )


def _celebration_plain_message(person: dict) -> str:
    name = person["username"]
    if person["celebration_type"] == "BIRTHDAY":
        return f"Wishing {name} a very happy birthday! 🎂"
    years = person.get("years")
    return f"Congratulations to {name} on their {years}-year work anniversary! 🏆"