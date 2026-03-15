from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prisma import Prisma

from src.common.dependencies import check_route_permission, CurrentUser
from src.prisma.client import db
from src.notifications.email_sender import EmailSender, SMTPConfig

from .schemas import DigestEmailRequest, DigestResponse, WeeklyDigestData
from .service import DigestService

router = APIRouter(prefix="/digest", tags=["Weekly Digest"])

_ADMIN_ROLES = {"SUPER_ADMIN", "HR_ADMIN"}

# ── Dependency factories ───────────────────────────────────────────────────────

def get_db() -> Prisma:
    return db


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
        description="Monday of the desired week in ISO 8601. Defaults to last completed week.",
        example="2026-02-23T00:00:00Z",
    ),
    manager_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Scope digest to direct reports of this manager UUID. "
            "Omit to get platform-wide totals (admins) or your own team (managers)."
        ),
    ),
    current_user: CurrentUser = Depends(check_route_permission),
    svc: DigestService = Depends(get_digest_service),
):
    """
    Return a week's recognition summary as JSON (for the dashboard preview).

    Scoping rules:
      - explicit manager_id supplied → always scope to that manager's team
      - no manager_id, caller is SUPER_ADMIN or HR_ADMIN → platform-wide (no filter)
      - no manager_id, caller is MANAGER/EMPLOYEE → scope to their own team
    """
    if manager_id:
        # Explicit manager selected — scope to that team.
        effective_manager_id: Optional[str] = str(manager_id)
    elif any(r in _ADMIN_ROLES for r in current_user.roles):
        # Admin with no manager selected → platform-wide, no filter.
        effective_manager_id = None
    else:
        # Non-admin with no manager selected → default to own team.
        effective_manager_id = current_user.id

    return await svc.get_digest_data(
        week_start=week_start,
        manager_id=effective_manager_id,
    )


# ── Email delivery endpoint (POST) ────────────────────────────────────────────

@router.post("/send", status_code=status.HTTP_200_OK, response_model=DigestResponse)
async def send_weekly_digest(
    payload: DigestEmailRequest,
    current_user: CurrentUser = Depends(check_route_permission),
    svc: DigestService = Depends(get_digest_service),
):
    """
    Generate a team-scoped weekly digest and deliver it to the manager's email.

    - manager_email — recipient address (must be a manager / admin)
    - manager_id    — scope digest to this manager's direct reports
    - week_start    — optional Monday date (UTC); defaults to last completed week

    FIX: Rejects a future week_start with 422 so callers get an explicit error
    instead of a silently empty digest.
    """
    # Guard: reject future week_start to avoid silent empty digests.
    if payload.week_start is not None:
        now_utc = datetime.now(tz=timezone.utc)
        ws = payload.week_start
        # Normalise to UTC-aware for comparison.
        if ws.tzinfo is None:
            ws = ws.replace(tzinfo=timezone.utc)
        if ws > now_utc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="week_start must not be in the future.",
            )

    return await svc.send_digest_email(
        manager_email=payload.manager_email,
        manager_id=str(payload.manager_id) if payload.manager_id else None,
        week_start=payload.week_start,
    )