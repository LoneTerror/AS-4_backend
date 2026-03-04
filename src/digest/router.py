from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from prisma import Prisma

from src.employees.dependencies import get_db
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.recognition.dependencies import require_roles   # MANAGER / ADMIN guard

from .schemas import DigestEmailRequest, DigestResponse, WeeklyDigestData
from .service import DigestService

router = APIRouter(prefix="/v1/digest", tags=["Weekly Digest"])


# ── Dependency factories ───────────────────────────────────────────────────────

def get_email_sender() -> EmailSender:
    return EmailSender(SMTPConfig.from_env())


def get_digest_service(
    db: Prisma = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
) -> DigestService:
    return DigestService(db, sender)


# ── Dashboard endpoint (GET) ───────────────────────────────────────────────────

@router.get("", response_model=WeeklyDigestData)
async def get_weekly_digest(
    week_start: Optional[datetime] = Query(
        default=None,
        description="Monday of the desired week in ISO 8601 e.g. 2026-02-23T00:00:00Z. Defaults to last completed week.",
        example="2026-02-23T00:00:00Z",
    ),
    current_user=Depends(require_roles("MANAGER", "ADMIN", "SUPER_ADMIN")),
    svc: DigestService = Depends(get_digest_service),
):
    """
    Return a week's recognition summary as JSON (for the dashboard).
    Pass `week_start` to select a specific week, or omit to get last completed week.

    Roles: MANAGER, ADMIN, SUPER_ADMIN
    """
    return await svc.get_digest_data(week_start=week_start)


# ── Email delivery endpoint (POST) ────────────────────────────────────────────

@router.post("/send", status_code=status.HTTP_200_OK, response_model=DigestResponse)
async def send_weekly_digest(
    payload: DigestEmailRequest,
    current_user=Depends(require_roles("MANAGER", "ADMIN", "SUPER_ADMIN")),
    svc: DigestService = Depends(get_digest_service),
):
    """
    Generate the weekly recognition digest and deliver it to the manager's email.

    - `manager_email` — recipient address
    - `week_start`    — optional Monday date (UTC); defaults to last completed week

    Roles: MANAGER, ADMIN, SUPER_ADMIN

    Body example:
    {
        "manager_email": "manager@company.com",
        "week_start": "2026-02-23T00:00:00Z"
    }
    """
    return await svc.send_digest_email(
        manager_email=payload.manager_email,
        week_start=payload.week_start,
    )