"""
digest/service.py
──────────────────
Orchestrates:
  1. Fetch weekly data from the reviews table (scoped to manager's team)
  2. Build branded HTML
  3. Send via EmailSender

BUG FIX:
  send_digest_email now raises ValueError for a future week_start before
  hitting the DB, giving callers a clear error instead of a silent empty
  digest. (The router's 422 guard covers the HTTP path; this layer protects
  direct Python callers such as the worker.)
"""

import logging
from datetime import datetime, timezone
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
        manager_id: Optional[str] = None,
    ) -> WeeklyDigestData:
        """
        Return digest stats without sending an email (used by dashboard endpoint).
        Scoped to manager's direct reports when manager_id is provided.
        """
        return await fetch_weekly_digest_data(
            self._db,
            week_start=week_start,
            manager_id=manager_id,
        )

    async def send_digest_email(
        self,
        *,
        manager_email: str,
        manager_id: Optional[str] = None,
        week_start: Optional[datetime] = None,
    ) -> DigestResponse:
        """
        Fetch team-scoped digest data, build HTML, and deliver to manager's email.

        FIX: Rejects a future week_start immediately with a clear ValueError so
        callers (including the worker) never receive a silent empty digest.
        """
        # Guard: reject a future week_start.
        if week_start is not None:
            now_utc = datetime.now(tz=timezone.utc)
            ws = week_start if week_start.tzinfo else week_start.replace(tzinfo=timezone.utc)
            if ws > now_utc:
                return DigestResponse(
                    success=False,
                    message="week_start must not be in the future.",
                )

        try:
            data = await fetch_weekly_digest_data(
                self._db,
                week_start=week_start,
                manager_id=manager_id,
            )
            subject, html = build_digest_html(data)

            await self._sender.send_notification_email(
                to_email=manager_email,
                subject=subject,
                body_html=html,
            )

            logger.info(
                "Weekly digest sent to %s | manager=%s week=%s recognitions=%d",
                manager_email,
                manager_id or "platform-wide",
                data.week_start.date(),
                data.total_recognitions,
            )
            return DigestResponse(
                success=True,
                message=f"Digest sent to {manager_email}",
                data=data,
            )

        except Exception:
            logger.exception(
                "DigestService: failed to send digest to %s (manager=%s)",
                manager_email,
                manager_id,
            )
            return DigestResponse(
                success=False,
                message="Failed to generate or send digest. Check server logs.",
            )   