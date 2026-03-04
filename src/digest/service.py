"""
digest/service.py
──────────────────
Orchestrates:
  1. Fetch weekly data from the reviews table
  2. Build branded HTML
  3. Send via EmailSender
"""

import logging
from datetime import datetime
from typing import Optional

from prisma import Prisma

from src.notifications.email_sender import EmailSender

from .email_builder import build_digest_html
from .queries import fetch_weekly_digest_data
from .schemas import DigestResponse, WeeklyDigestData

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, db: Prisma, email_sender: EmailSender) -> None:
        self._db = db
        self._sender = email_sender

    async def get_digest_data(
        self,
        week_start: Optional[datetime] = None,
    ) -> WeeklyDigestData:
        """Return digest stats without sending an email (used by dashboard endpoint)."""
        return await fetch_weekly_digest_data(self._db, week_start)

    async def send_digest_email(
        self,
        *,
        manager_email: str,
        week_start: Optional[datetime] = None,
    ) -> DigestResponse:
        """Fetch digest data, build HTML, and deliver to the manager's email."""
        try:
            data = await fetch_weekly_digest_data(self._db, week_start)
            subject, html = build_digest_html(data)

            await self._sender.send_notification_email(
                to_email=manager_email,
                subject=subject,
                body_html=html,
            )

            logger.info(
                "Weekly digest sent to %s | week=%s recognitions=%d",
                manager_email,
                data.week_start.date(),
                data.total_recognitions,
            )
            return DigestResponse(
                success=True,
                message=f"Digest sent to {manager_email}",
                data=data,
            )

        except Exception:
            logger.exception("DigestService: failed to send digest to %s", manager_email)
            return DigestResponse(
                success=False,
                message="Failed to generate or send digest. Check server logs.",
            )
