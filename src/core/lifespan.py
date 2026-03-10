# src/core/lifespan.py

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prisma import Prisma

from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.notifications.slack_sender import SlackSender, SlackConfig
from src.notifications.worker import email_worker_loop, celebration_worker_loop

logger = logging.getLogger(__name__)

db = Prisma()


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

    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    # Slack is optional — app starts normally even if env vars are missing
    slack_sender: SlackSender | None = None
    try:
        slack_config = SlackConfig.from_env()
        slack_sender = SlackSender(slack_config)
        logger.info("Slack sender initialised.")
    except KeyError as e:
        logger.warning("Slack disabled — missing env var: %s", e)

    worker_task = asyncio.create_task(
        email_worker_loop(db, email_sender, redis, slack_sender),
        name="email_notification_worker",
    )
    celebration_task = asyncio.create_task(
        celebration_worker_loop(db, email_sender, redis, slack_sender),
        name="celebration_notification_worker",
    )
    logger.info("Email worker task created.")
    logger.info("Celebration worker task created.")

    yield  # ← app is live

    # ── Shutdown ───────────────────────────────────────────────────────────
    for task in (worker_task, celebration_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Workers stopped.")
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