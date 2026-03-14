"""
digest/worker.py
─────────────────
Weekly digest worker — fires every Monday at 08:00 UTC.
Mirrors the asyncio-task pattern used in notifications/worker.py.

The worker:
  1. Wakes up every minute to check if it is Monday 08:00 UTC.
  2. Uses an idempotency guard (checks whether a digest notification was
     already sent today) so a restart never double-sends.
  3. Fetches all ACTIVE employees whose role includes MANAGER, along with
     their employee_id so each digest can be scoped to their team.
  4. Sends each manager their team-scoped digest email concurrently.

BUG FIXES (original):
  1. startswith → startsWith (Prisma camelCase) in _already_sent_today.
  2. Added _running flag to prevent concurrent runs within the same process.

BUG FIX (this revision):
  3. _get_managers now returns list[tuple[str, str]] — (email, employee_id) —
     instead of list[str].  _run_digest passes each manager's employee_id as
     manager_id to send_digest_email so every manager receives a digest
     scoped to their own team's recognitions.  Previously manager_id was
     never forwarded, so every manager received an identical platform-wide
     digest — making the team-scoping logic in queries.py dead code.
"""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS: int = 60        # wake up every minute
DIGEST_WEEKDAY: int = 0                # 0 = Monday
DIGEST_HOUR_UTC: int = 8

# Belt-and-suspenders in-process lock — prevents a second concurrent run if
# the previous send is still in flight when the next poll tick fires.
_running: bool = False


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
    created today. Written by _write_sentinel before sending begins.

    FIX: Prisma filter keys are camelCase — startsWith not startswith.
    """
    from datetime import date

    start_of_day = datetime.combine(
        date.today(), datetime.min.time()
    ).replace(tzinfo=timezone.utc)

    existing = await db.notifications.find_first(
        where={
            "type":       "SYSTEM",
            "title":      {"startsWith": "[DIGEST]"},   # camelCase required
            "created_at": {"gte": start_of_day},
        }
    )
    return existing is not None


async def _write_sentinel(db) -> None:
    """Write a sentinel row so a crash mid-run doesn't cause a double-send."""
    from datetime import date

    employee_id = await _any_employee_id(db)

    await db.notifications.create(
        data={
            "employee_id": employee_id,
            "title":       f"[DIGEST] Weekly digest sentinel {date.today().isoformat()}",
            "message":     "Automated digest worker sentinel — do not display.",
            "type":        "SYSTEM",
            "is_read":     True,
            "email_sent":  True,
        }
    )


async def _any_employee_id(db) -> str:
    emp = await db.employees.find_first()
    if emp is None:
        raise RuntimeError("Digest worker: no employees found in DB")
    return str(emp.employee_id)


async def _get_managers(db) -> list[tuple[str, str]]:
    """
    Return (email, employee_id) for all ACTIVE employees whose active
    role_code contains 'MANAGER' (case-insensitive).

    FIX: Previously returned only list[str] of emails, discarding employee_id.
    The employee_id is required to scope each digest to the manager's own team.
    """
    active_employees = await db.employees.find_many(
        include={
            "status_master_employees_status_idTostatus_master": True,
            "employee_roles_employee_roles_employee_idToemployees": {
                "include": {"roles": True},
                "where":   {"is_active": True},
            },
        }
    )

    managers: list[tuple[str, str]] = []
    for emp in active_employees:
        status = emp.status_master_employees_status_idTostatus_master
        if status is None or status.status_code != "ACTIVE":
            continue

        for er in (emp.employee_roles_employee_roles_employee_idToemployees or []):
            role = er.roles
            if role and "MANAGER" in role.role_code.upper():
                managers.append((emp.email, str(emp.employee_id)))
                break  # one entry per employee is enough

    return managers


async def _run_digest(db, email_sender) -> None:
    global _running

    # In-process lock — skip if a previous run is still in flight.
    if _running:
        logger.debug("Digest worker: previous run still in progress — skipping tick.")
        return

    # DB sentinel — skip if already sent today (survives restarts).
    if await _already_sent_today(db):
        logger.info("Digest worker: sentinel found — skipping duplicate send.")
        return

    _running = True
    try:
        # Write sentinel FIRST so a crash mid-send doesn't cause a retry loop.
        await _write_sentinel(db)

        managers = await _get_managers(db)
        if not managers:
            logger.warning("Digest worker: no manager emails found — nothing sent.")
            return

        from src.digest.service import DigestService
        svc = DigestService(db, email_sender)

        async def _send_one(email: str, manager_id: str) -> None:
            # FIX: pass manager_id so the digest is scoped to this manager's team.
            result = await svc.send_digest_email(
                manager_email=email,
                manager_id=manager_id,
            )
            if not result.success:
                logger.warning("Digest worker: failed to send to %s", email)

        await asyncio.gather(*[_send_one(email, mid) for email, mid in managers])
        logger.info(
            "Digest worker: digest sent to %d manager(s) this week.",
            len(managers),
        )
    finally:
        _running = False        