"""
digest/worker.py
─────────────────
Weekly digest worker — fires every Monday at 08:00 UTC.
Mirrors the asyncio-task pattern used in notifications/worker.py.

The worker:
  1. Wakes up every minute to check if it is Monday 08:00 UTC.
  2. Uses an idempotency guard (checks whether a digest notification was
     already sent today) so a restart never double-sends.
  3. Fetches all ACTIVE employees whose role includes MANAGER.
  4. Sends each manager their digest email concurrently.
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 60        # wake up every minute
DIGEST_WEEKDAY: int = 0                # 0 = Monday
DIGEST_HOUR_UTC: int = 8


async def digest_worker_loop(db, email_sender) -> None:
    """
    Entry point — register this as an asyncio Task in your lifespan.

    Example (in your service's lifespan):

        from src.digest.worker import digest_worker_loop
        from src.notifications.email_sender import EmailSender, SMTPConfig

        @asynccontextmanager
        async def lifespan(app):
            await connect_with_retry()
            sender = EmailSender(SMTPConfig.from_env())
            task = asyncio.create_task(digest_worker_loop(db, sender))
            yield
            task.cancel()
    """
    logger.info(
        "Digest worker started — fires Mondays at %02d:00 UTC",
        DIGEST_HOUR_UTC,
    )
    while True:
        try:
            now = datetime.now(tz=timezone.utc)
            if now.weekday() == DIGEST_WEEKDAY and now.hour == DIGEST_HOUR_UTC:
                await _run_digest(db, email_sender)
        except asyncio.CancelledError:
            logger.info("Digest worker shutting down.")
            raise
        except Exception:
            logger.exception("Digest worker: unexpected error")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def _already_sent_today(db) -> bool:
    """
    Idempotency guard.
    Checks for a SYSTEM notification whose title starts with '[DIGEST]'
    created today. Written by _run_digest before sending begins.
    """
    from datetime import date

    start_of_day = datetime.combine(
        date.today(), datetime.min.time()
    ).replace(tzinfo=timezone.utc)

    existing = await db.notifications.find_first(
        where={
            "type": "SYSTEM",
            "title": {"startswith": "[DIGEST]"},
            "created_at": {"gte": start_of_day},
        }
    )
    return existing is not None


async def _write_sentinel(db) -> None:
    """Write a sentinel row so a crash mid-run doesn't cause a double-send."""
    from datetime import date

    await db.notifications.create(
        data={
            "employee_id": await _any_employee_id(db),
            "title": f"[DIGEST] Weekly digest sentinel {date.today().isoformat()}",
            "message": "Automated digest worker sentinel — do not display.",
            "type": "SYSTEM",
            "is_read": True,
            "email_sent": True,
        }
    )


async def _any_employee_id(db) -> str:
    emp = await db.employees.find_first()
    if emp is None:
        raise RuntimeError("Digest worker: no employees found in DB")
    return str(emp.employee_id)


async def _get_manager_emails(db) -> list[str]:
    """
    Return email addresses for all ACTIVE employees whose role_code
    contains 'MANAGER' (case-insensitive).
    """
    active_employees = await db.employees.find_many(
        include={
            "status_master_employees_status_idTostatus_master": True,
            "employee_roles_employee_roles_employee_idToemployees": {
                "include": {"roles": True},
                "where": {"is_active": True},
            },
        }
    )

    emails: list[str] = []
    for emp in active_employees:
        status = emp.status_master_employees_status_idTostatus_master
        if status is None or status.status_code != "ACTIVE":
            continue

        for er in (emp.employee_roles_employee_roles_employee_idToemployees or []):
            role = er.roles
            if role and "MANAGER" in role.role_code.upper():
                emails.append(emp.email)
                break  # one entry per employee is enough

    return emails


async def _run_digest(db, email_sender) -> None:
    from src.digest.service import DigestService

    if await _already_sent_today(db):
        logger.info("Digest worker: sentinel found — skipping duplicate send.")
        return

    await _write_sentinel(db)

    manager_emails = await _get_manager_emails(db)
    if not manager_emails:
        logger.warning("Digest worker: no manager emails found — nothing sent.")
        return

    svc = DigestService(db, email_sender)

    async def _send_one(email: str) -> None:
        result = await svc.send_digest_email(manager_email=email)
        if not result.success:
            logger.warning("Digest worker: failed to send to %s", email)

    results = await asyncio.gather(*[_send_one(e) for e in manager_emails])
    logger.info(
        "Digest worker: digest sent to %d manager(s) this week.", len(manager_emails)
    )
