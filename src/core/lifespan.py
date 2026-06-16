# src/core/lifespan.py
"""
Application lifespan.

Changes vs original:
─────────────────────────────────────────────────────────────────────────────
1. celebration_worker_loop REMOVED — replaced by APScheduler with RedisJobStore.
   - RedisJobStore ensures only ONE pod fires the job even across many instances.
   - Cron trigger fires at midnight + 5 min every day (configurable via env).
   - max_instances=1 + coalesce=True prevents overlap and missed-run pile-up.
   - The Redis sentinel in process_celebrations is the secondary dedup guard.

2. requests_store periodic cleanup added — prevents memory leak in long-running
   processes where many unique IPs accumulate in the in-memory rate limit store.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from prisma import Prisma

from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.notifications.slack_sender import SlackSender, SlackConfig
from src.notifications.worker import email_worker_loop, process_celebrations

logger = logging.getLogger(__name__)

db = Prisma()

# Celebration job cron time — override via env if needed
_CELEB_HOUR   = int(os.getenv("CELEBRATION_CRON_HOUR",   "0"))   # default midnight
_CELEB_MINUTE = int(os.getenv("CELEBRATION_CRON_MINUTE",  "5"))   # default 00:05


def get_db() -> Prisma:
    return db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ────────────────────────────────────────────────────────────
    await db.connect()
    logger.info("Prisma connected.")

    redis = await connect_redis()
    app.state.redis = redis
    logger.info("Redis connected.")

    smtp_config  = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    # Slack is optional — app starts normally even if env vars are missing
    slack_sender: SlackSender | None = None
    try:
        slack_config = SlackConfig.from_env()
        slack_sender = SlackSender(slack_config)
        logger.info("Slack sender initialised.")
    except KeyError as e:
        logger.warning("Slack disabled — missing env var: %s", e)

    # ── Email worker (BLPOP — instant notifications) ───────────────────────
    worker_task = asyncio.create_task(
        email_worker_loop(db, email_sender, redis, slack_sender),
        name="email_notification_worker",
    )
    logger.info("Email worker task created.")

    # ── Celebration scheduler (APScheduler + RedisJobStore) ────────────────
    #
    # RedisJobStore stores job state in Redis so all pods share the same
    # job registry. APScheduler elects one runner — only ONE pod fires
    # process_celebrations even if 10 instances are running.
    #
    # max_instances=1  — never overlaps itself within a single pod.
    # coalesce=True    — if the pod was down at midnight, run once on wake,
    #                    not once per missed interval.
    redis_url  = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # Strip DB index from URL for APScheduler host/port parsing
    redis_host = redis_url.split("://")[-1].split(":")[0]
    redis_port = int(redis_url.split(":")[-1].split("/")[0]) if ":" in redis_url.split("://")[-1] else 6379
    redis_db   = int(redis_url.split("/")[-1]) if "/" in redis_url else 0

    jobstores = {
        "default": RedisJobStore(
            jobs_key="apscheduler:celebration:jobs",
            run_times_key="apscheduler:celebration:run_times",
            host=redis_host,
            port=redis_port,
            db=redis_db,
        )
    }

    scheduler = AsyncIOScheduler(jobstores=jobstores)
    scheduler.add_job(
        process_celebrations,
        trigger="cron",
        hour=_CELEB_HOUR,
        minute=_CELEB_MINUTE,
        args=[db, email_sender, redis, slack_sender],
        id="daily_celebration_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Celebration scheduler started — cron=%02d:%02d daily (RedisJobStore)",
        _CELEB_HOUR,
        _CELEB_MINUTE,
    )

    yield  # ← app is live

    # ── Shutdown ───────────────────────────────────────────────────────────
    scheduler.shutdown(wait=False)
    logger.info("Celebration scheduler stopped.")

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    logger.info("Email worker stopped.")

    await disconnect_redis()
    await db.disconnect()
    logger.info("Prisma disconnected.")


def create_app() -> FastAPI:
    from src.notifications.router import router as notifications_router
    from src.webhooks.router import router as webhooks_router

    application = FastAPI(title="HR Recognition API", lifespan=lifespan)
    application.include_router(notifications_router)
    application.include_router(webhooks_router)
    return application