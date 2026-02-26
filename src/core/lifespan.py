# src/core/lifespan.py
#
# Drop-in replacement for (or extension of) your existing lifespan handler.
# The email worker is started as an asyncio.Task so it runs on the same
# event loop as the rest of the app without blocking request handling.

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prisma import Prisma

from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.worker import email_worker_loop, celebration_worker_loop

logger = logging.getLogger(__name__)

# ── Shared Prisma client ───────────────────────────────────────────────────────
# Define once at module level; imported by routers via get_db().
db = Prisma()


def get_db() -> Prisma:
    """FastAPI dependency — yields the connected Prisma instance."""
    return db


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup
    ───────
    1. Connect Prisma.
    2. Build EmailSender from environment.
    3. Spawn the background email worker as a Task.

    Shutdown
    ────────
    1. Cancel the worker task (triggers CancelledError in the loop).
    2. Await its completion.
    3. Disconnect Prisma.
    """

    # ── Startup ────────────────────────────────────────────────────────────
    await db.connect()
    logger.info("Prisma connected.")

    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    worker_task = asyncio.create_task(
        email_worker_loop(db, email_sender),
        name="email_notification_worker",
    )
    celebration_task = asyncio.create_task(
        celebration_worker_loop(db, email_sender),
        name="celebration_notification_worker",
    )
    logger.info("Email notification worker task created.")
    logger.info("Celebration worker task created.")

    yield  # ← app is running and serving requests

    # ── Shutdown ───────────────────────────────────────────────────────────
    for task in (worker_task, celebration_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # expected — worker exited cleanly
    logger.info("Email worker stopped.")
    logger.info("Celebration worker stopped.")

    await db.disconnect()
    logger.info("Prisma disconnected.")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Application factory.  Import and call this in your main entry point.
    """
    from src.notifications.router import router as notifications_router
    # from src.auth.router import router as auth_router  # your existing routers
    # from src.reviews.router import router as reviews_router

    application = FastAPI(
        title="HR Recognition API",
        lifespan=lifespan,
    )

    application.include_router(notifications_router)
    # application.include_router(auth_router)
    # application.include_router(reviews_router)

    return application