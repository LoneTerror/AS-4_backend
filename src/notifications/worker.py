# src/notifications/worker.py
"""
Background Email + Slack Worker
════════════════════════════════
Architecture: DB polling → Redis queue (BLPOP)

Key fixes vs original:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. AT-MOST-ONCE DELIVERY (fixes duplicate emails on restart)
   - Mark email_sent=True in DB BEFORE sending email/Slack.
   - If the send fails, revert email_sent=False so recovery can retry.
   - Prevents the race: "process crashes between send() and mark_sent()"
     from causing duplicates.

2. REDIS CLAIM LOCK (fixes duplicate processing across instances / rapid restarts)
   - Before processing any notification, atomically SET a Redis key with NX+EX.
   - If the key already exists, another worker instance claimed it — skip silently.
   - Lock TTL = 10 minutes (well beyond any reasonable SMTP timeout).

3. SAFE RECOVERY WINDOW (fixes re-queuing of in-flight notifications)
   - Recovery query excludes notifications created in the last 5 minutes.
   - Notifications that young were likely mid-processing when the server died.
   - They are covered by the claim lock anyway, but this avoids unnecessary
     re-queuing noise.

4. RETRY CAP (fixes infinite re-queue loop when sending keeps failing)
   - _mark_email_unsent now increments a send_attempts counter.
   - _recover_pending skips rows that have already failed 3+ times.
   - Those rows are left with email_sent=False for manual inspection.

5. CELEBRATION ROWS SKIPPED IN REGULAR QUEUE (fixes duplicate celebration emails)
   - Celebration notification rows are enqueued via create_notification like any
     other row, but they are fully managed by the celebration worker.
   - _process_one now detects type==CELEBRATION and marks the row sent without
     sending any email, so the regular worker never double-delivers them.

6. ONE-SHOT RECOVERY PER DAY (fixes re-queuing on every restart)
   - _recover_pending checks/sets the notify:recovery_done Redis key.
   - Subsequent restarts within the same 24-hour window skip recovery.
   - The key expires automatically so recovery runs fresh each day.

7. CELEBRATION DEDUP IS UNCHANGED — sentinel written before broadcast loop
   is the correct guard. The at-most-once fix above also applies to
   individual celebration notification rows.

8. APSCHEDULER REPLACES celebration_worker_loop (fixes multi-instance duplicates)
   - celebration_worker_loop removed entirely.
   - _process_celebrations is now a plain async function called by APScheduler
     via RedisJobStore — only ONE pod fires the job even across many instances.
   - Scheduler is set up in lifespan.py.

9. SMTP RATE LIMITING (fixes SMTP provider throttling / blacklisting at scale)
   - _notify_recipient now throttles to EMAILS_PER_SECOND.
   - Prevents hitting SendGrid / SES per-second limits on large broadcasts.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from opentelemetry import trace

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
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# How long a claim lock is held in Redis.
# Must be longer than the worst-case send time (SMTP + Slack combined).
_CLAIM_TTL_SECONDS = 600  # 10 minutes

# Notifications younger than this are assumed to be mid-processing from the
# previous server run and are excluded from startup recovery re-queuing.
_RECOVERY_GRACE_SECONDS = 300  # 5 minutes

# Maximum number of send attempts before a notification is abandoned.
# Rows that hit this cap are left with email_sent=False for manual inspection.
_MAX_SEND_ATTEMPTS = 3

# Redis key that gates one-shot recovery per 24-hour window.
_RECOVERY_DONE_KEY = "notify:recovery_done"

# SMTP rate limit — emails sent per second during celebration broadcasts.
# Stay well under SendGrid (100/s) and SES (14/s) default limits.
# Set conservatively; increase once you confirm your provider's limits.
EMAILS_PER_SECOND = 10


# ── Claim lock ────────────────────────────────────────────────────────────────

async def _try_claim(r: aioredis.Redis, notification_id: str) -> bool:
    """
    Atomically claim a notification for processing.

    Uses SET NX EX — the claim succeeds only if no other worker instance
    has already set this key. Returns True if this worker owns it.

    The lock is intentionally NOT released after processing — it expires
    naturally after _CLAIM_TTL_SECONDS. This prevents a slow second worker
    from re-processing a notification that the first worker already finished.

    Raw r.set() used intentionally — requires NX atomicity not available
    in cache helpers.
    """
    key = f"processing:{notification_id}"
    try:
        result = await r.set(key, "1", nx=True, ex=_CLAIM_TTL_SECONDS)
        return result is True
    except Exception as exc:
        # If Redis is unavailable, allow processing to continue — the DB
        # email_sent flag is the fallback dedup guard.
        logger.warning("_try_claim(%s) Redis error — proceeding without lock: %s", notification_id, exc)
        return True


# ── Startup recovery ──────────────────────────────────────────────────────────

async def _recover_pending(db: "Prisma", r: aioredis.Redis) -> int:
    """
    On startup, find notifications that were never sent and re-queue them.

    Checks notify:recovery_done before doing anything. If the key exists
    (set within the last 24h), recovery is skipped entirely.
    This prevents every restart from re-queuing the same notifications.

    Excludes rows whose send_attempts >= _MAX_SEND_ATTEMPTS so
    persistently-failing notifications do not loop forever.

    Excludes notifications younger than _RECOVERY_GRACE_SECONDS — those
    were likely mid-processing when the previous instance died and will be
    handled by the claim lock if a duplicate somehow arrives.

    Runs once per worker startup (gated by notify:recovery_done).

    Raw r.exists() / r.set() used intentionally — process-coordination
    flags, not cached data. L1/L2 cache helpers are not appropriate here.
    """
    with tracer.start_as_current_span("worker_startup_recovery") as span:

        try:
            already_done = await r.exists(_RECOVERY_DONE_KEY)
        except Exception:
            already_done = False  # Redis unavailable — run recovery anyway

        if already_done:
            logger.info("Worker recovery: notify:recovery_done key present — skipping recovery.")
            span.set_attribute("recovery.skipped", True)
            return 0

        cutoff_upper = datetime.now(tz=timezone.utc)
        cutoff_lower = cutoff_upper - timedelta(seconds=_RECOVERY_GRACE_SECONDS)

        pending = await db.notifications.find_many(
            where={
                "email_sent": False,
                "type": {"not": "CELEBRATION"},
                "send_attempts": {"lt": _MAX_SEND_ATTEMPTS},
                "created_at": {
                    "lt": cutoff_lower,
                },
            },
            order={"created_at": "asc"},
        )
        span.set_attribute("recovery.pending_count", len(pending))

        if pending:
            pipe = r.pipeline()
            for n in pending:
                pipe.lpush(QUEUE_KEY, str(n.notification_id))
            await pipe.execute()
            logger.info(
                "Worker recovery: re-queued %d pending notification(s) "
                "(older than %ds, attempts < %d)",
                len(pending),
                _RECOVERY_GRACE_SECONDS,
                _MAX_SEND_ATTEMPTS,
            )

        try:
            await r.set(_RECOVERY_DONE_KEY, "1", ex=86400)
        except Exception as exc:
            logger.warning("Worker recovery: failed to set recovery_done key — %s", exc)

        return len(pending)


# ── Employee / Slack UID helpers ──────────────────────────────────────────────

async def _get_employee(db: "Prisma", r: aioredis.Redis, employee_id: str) -> dict | None:
    """Fetch employee with Redis L1/L2 cache. Falls back to DB on miss."""
    cached = await get_cached_employee(r, employee_id)
    if cached:
        return cached

    emp = await db.employees.find_unique(where={"employee_id": employee_id})
    if emp is None:
        return None

    emp_dict = {
        "employee_id": str(emp.employee_id),
        "email": emp.email,
        "username": emp.username,
    }
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
        return cached if cached else None  # "" = cached "not found"

    uid = await slack.get_user_id_by_email(email)
    await set_cached_slack_uid(r, email, uid)
    return uid


# ── Mark helpers ──────────────────────────────────────────────────────────────

async def _mark_email_sent(db: "Prisma", notification_id: str) -> None:
    await db.notifications.update(
        where={"notification_id": notification_id},
        data={"email_sent": True},
    )


async def _mark_email_unsent(db: "Prisma", notification_id: str) -> None:
    """
    Revert email_sent back to False so recovery can retry on next restart.
    Called when sending fails after we already flipped the flag.
    Also increments send_attempts so that notifications which keep
    failing are eventually abandoned by _recover_pending after _MAX_SEND_ATTEMPTS.
    """
    try:
        await db.notifications.update(
            where={"notification_id": notification_id},
            data={
                "email_sent": False,
                "send_attempts": {"increment": 1},
            },
        )
    except Exception as exc:
        logger.warning(
            "_mark_email_unsent(%s) failed — notification may be lost: %s",
            notification_id,
            exc,
        )


# ── Core processor ────────────────────────────────────────────────────────────

async def _process_one(
    db: "Prisma",
    sender: "EmailSender",
    slack: "SlackSender | None",
    r: aioredis.Redis,
    notification_id: str,
) -> bool:
    from .email_sender import build_notification_html

    with tracer.start_as_current_span("process_single_notification") as span:
        span.set_attribute("notification.id", notification_id)

        # ── Step 1: Claim lock ────────────────────────────────────────────────
        claimed = await _try_claim(r, notification_id)
        if not claimed:
            span.set_attribute("notification.status", "skipped_claim_lost")
            logger.debug(
                "Worker: notification %s already claimed by another instance — skipping",
                notification_id,
            )
            return True

        # ── Step 2: Fetch from DB ─────────────────────────────────────────────
        notification = await db.notifications.find_unique(
            where={"notification_id": notification_id}
        )
        if notification is None:
            span.set_attribute("notification.status", "not_found_in_db")
            logger.warning(
                "Worker: notification %s not found in DB — skipping",
                notification_id,
            )
            return False

        # ── Step 3: Idempotency guard ─────────────────────────────────────────
        if notification.email_sent:
            span.set_attribute("notification.status", "already_sent")
            logger.debug(
                "Worker: notification %s already sent — skipping duplicate",
                notification_id,
            )
            return True

        # ── Step 3b: Skip celebration rows ────────────────────────────────────
        if notification.type == "CELEBRATION":
            span.set_attribute("notification.status", "skipped_celebration_type")
            logger.debug(
                "Worker: notification %s is type CELEBRATION — "
                "skipping regular delivery, marking sent to drain queue.",
                notification_id,
            )
            await _mark_email_sent(db, notification_id)
            return True

        span.set_attribute("notification.type", notification.type)

        # ── Step 4: Retry cap guard ───────────────────────────────────────────
        attempts = getattr(notification, "send_attempts", 0) or 0
        if attempts >= _MAX_SEND_ATTEMPTS:
            span.set_attribute("notification.status", "abandoned_max_attempts")
            logger.error(
                "Worker: notification %s has failed %d times (max=%d) — "
                "abandoning. Manual intervention required.",
                notification_id,
                attempts,
                _MAX_SEND_ATTEMPTS,
            )
            return False

        # ── Step 5: Resolve employee ──────────────────────────────────────────
        employee = await _get_employee(db, r, str(notification.employee_id))
        if employee is None:
            span.set_attribute("notification.status", "employee_not_found")
            logger.warning(
                "Worker: employee %s not found — marking sent to avoid retry loop",
                notification.employee_id,
            )
            await _mark_email_sent(db, notification_id)
            return False

        # ── Step 6: Claim the row in DB BEFORE sending ────────────────────────
        await _mark_email_sent(db, notification_id)

        # ── Step 7: Send email + Slack concurrently ───────────────────────────
        try:
            html = build_notification_html(
                title=notification.title,
                message=notification.message,
                type_=notification.type,
            )

            async def _email_coro() -> None:
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
                        with tracer.start_as_current_span("send_slack_dm"):
                            await slack.send_dm(
                                slack_user_id=uid,
                                title=notification.title,
                                message=notification.message,
                                type_=notification.type,
                            )
                except Exception:
                    logger.warning(
                        "Worker: Slack DM failed for notification %s — "
                        "email delivery unaffected",
                        notification_id,
                    )

            await asyncio.gather(_email_coro(), _slack_coro())
            span.set_attribute("notification.status", "success")
            return True

        except Exception as e:
            span.record_exception(e)
            span.set_attribute("notification.status", "failed")
            logger.exception(
                "Worker: failed to send notification %s — reverting email_sent flag "
                "(attempt %d/%d)",
                notification_id,
                attempts + 1,
                _MAX_SEND_ATTEMPTS,
            )
            await _mark_email_unsent(db, notification_id)
            return False


# ── Email worker loop ─────────────────────────────────────────────────────────

async def email_worker_loop(
    db: "Prisma",
    sender: "EmailSender",
    r: aioredis.Redis,
    slack: "SlackSender | None" = None,
) -> None:
    """
    Main worker loop.

    1. Startup: recover notifications missed while the process was down.
       Gated by notify:recovery_done so it runs at most once per 24h.
    2. Loop: BLPOP — blocks until a notification_id arrives in the queue.
       Zero DB queries when the queue is idle.
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
                continue  # timeout — loop back and block again

            success = await _process_one(db, sender, slack, r, notification_id)
            if success:
                logger.info("Worker: processed notification %s", notification_id)

        except asyncio.CancelledError:
            logger.info("Email worker shutting down.")
            raise
        except Exception:
            logger.exception("Email worker: unexpected error")
            await asyncio.sleep(2)


# ── Celebration processor (called by APScheduler — NOT a loop) ───────────────

async def process_celebrations(
    db: "Prisma",
    sender: "EmailSender",
    r: aioredis.Redis,
    slack: "SlackSender | None" = None,
) -> None:
    """
    Fire-and-forget celebration processor.

    This is NOT a loop. It is called by APScheduler at midnight every day
    via RedisJobStore — only ONE pod fires it even across many instances.

    RedisJobStore acts as a distributed lock so only one scheduler instance
    runs the job at the cron time. The Redis sentinel in _process_celebrations
    is the secondary dedup guard if the scheduler somehow fires twice.

    SMTP rate limiting: emails are sent in batches of EMAILS_PER_SECOND
    with a 1-second pause between batches to avoid hitting SMTP provider
    rate limits (SendGrid, SES etc.) at scale.
    """
    from .email_sender import build_celebration_html
    from .service import NotificationService
    from .schemas import NotificationType

    with tracer.start_as_current_span("check_daily_celebrations") as main_span:
        svc = NotificationService(db, redis=r)
        celebrants = await svc.get_employees_with_celebrations_today()
        main_span.set_attribute("celebrants.count", len(celebrants))

        if not celebrants:
            logger.debug("Celebration worker: no celebrations today.")
            return

        all_active_employees = await _get_all_active_employees_cached(db, r)
        if not all_active_employees:
            logger.warning("Celebration worker: no active employees found.")
            return

        for person in celebrants:
            with tracer.start_as_current_span("broadcast_celebration") as person_span:
                person_span.set_attribute("celebrant.name", person["username"])
                person_span.set_attribute("celebration.type", person["celebration_type"])

                try:
                    # ── Sentinel check — primary dedup guard ──────────────────
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

                    # Write sentinel FIRST — before any email or notification row
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

                    # ── Slack broadcast (non-blocking, non-fatal) ─────────────
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

                    asyncio.create_task(_slack_broadcast())

                    # ── Rate-limited email broadcast ──────────────────────────
                    async def _notify_recipient(recipient: dict) -> bool:
                        is_celebrant = recipient["employee_id"] == str(person["employee_id"])
                        subject_to_send = personal_subject if is_celebrant else broadcast_subject
                        html_to_send    = personal_html    if is_celebrant else broadcast_html
                        plain_to_send   = (
                            (
                                f"[{person['celebration_type']}] Happy "
                                f"{person['celebration_type'].replace('_', ' ').title()}, "
                                f"{person['username']}!"
                            )
                            if is_celebrant
                            else broadcast_plain
                        )

                        try:
                            notification = await svc.create_notification(
                                employee_id=recipient["employee_id"],
                                title=subject_to_send,
                                message=plain_to_send,
                                type=NotificationType.CELEBRATION,
                            )
                            notif_id = str(notification["notification_id"])

                            await _mark_email_sent(db, notif_id)
                            try:
                                await sender.send_notification_email(
                                    to_email=recipient["email"],
                                    subject=subject_to_send,
                                    body_html=html_to_send,
                                )
                            except Exception:
                                await _mark_email_unsent(db, notif_id)
                                raise
                            return True
                        except Exception:
                            logger.exception(
                                "Celebration worker: failed to notify %s about %s's %s",
                                recipient["employee_id"],
                                person["username"],
                                person["celebration_type"],
                            )
                            return False

                    # Send in rate-limited batches
                    success_count = 0
                    for i, recipient in enumerate(all_active_employees):
                        ok = await _notify_recipient(recipient)
                        if ok:
                            success_count += 1
                        # Throttle: pause every EMAILS_PER_SECOND sends
                        if (i + 1) % EMAILS_PER_SECOND == 0:
                            await asyncio.sleep(1)

                    person_span.set_attribute("celebration.status", "success")
                    person_span.set_attribute("celebration.broadcast_count", success_count)
                    logger.info(
                        "Celebration worker: %s for %s → %d/%d employees notified",
                        person["celebration_type"],
                        person["username"],
                        success_count,
                        len(all_active_employees),
                    )

                except Exception as e:
                    person_span.record_exception(e)
                    person_span.set_attribute("celebration.status", "failed")
                    logger.exception(
                        "Celebration worker: failed to process celebration for %s",
                        person.get("employee_id"),
                    )


# ── Active employee cache helper ──────────────────────────────────────────────

async def _get_all_active_employees_cached(db: "Prisma", r: aioredis.Redis) -> list:
    """
    Returns all active employees for the celebration broadcast.
    Cached for 1h — the celebration job only runs daily anyway.
    """
    with tracer.start_as_current_span("fetch_active_employees_for_broadcast"):
        cached = await get_cached_celebration_employees(r)
        if cached is not None:
            logger.debug(
                "Celebration worker: active employees from cache (%d)", len(cached)
            )
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
                and e.status_master_employees_status_idTostatus_master.status_code
                == "ACTIVE"
            )
        ]
        await set_cached_celebration_employees(r, active)
        logger.debug(
            "Celebration worker: loaded %d active employees from DB → cached",
            len(active),
        )
        return active


# ── Plain text helper ─────────────────────────────────────────────────────────

def _celebration_plain_message(person: dict) -> str:
    name = person["username"]
    if person["celebration_type"] == "BIRTHDAY":
        return f"[BIRTHDAY] Today is {name}'s birthday! Wish them a great day."
    years = person.get("years")
    return (
        f"[WORK_ANNIVERSARY] {name} is celebrating their {years}-year "
        f"work anniversary today."
    )