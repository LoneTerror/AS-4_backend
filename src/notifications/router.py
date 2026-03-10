# src/notifications/router.py
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from prisma import Prisma

from src.common.dependencies import get_current_user, CurrentUser
from src.prisma.client import db
from .schemas import (
    AnnouncementCreateRequest,
    AnnouncementResponse,
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationType,
)
from .service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_db() -> Prisma:
    return db


def get_notification_service(
    request: Request,
    db: Prisma = Depends(get_db),
) -> NotificationService:
    # Pass Redis from app.state so create_notification() enqueues automatically
    r = getattr(request.app.state, "redis", None)
    return NotificationService(db, redis=r)


# ── Shared guard ───────────────────────────────────────────────────────────────

def _assert_valid_user_id(user_id: str) -> None:
    """
    Raise 401 if the user ID extracted from the token is not a valid UUID.

    This is a last-resort defence against a poisoned CurrentUser (e.g. the
    auth service returning null/None for user_id) reaching a Prisma query.
    Prisma stringifies None as "null", which causes a DataError at the DB
    layer and surfaces as an opaque 500 to the client.
    """
    try:
        UUID(user_id)
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identity in token — please re-authenticate",
        )


# ── Read routes ────────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)
    items = await svc.get_notifications(
        employee_id=current_user.id,
        limit=limit,
        unread_only=unread_only,
    )
    return NotificationListResponse(notifications=items, total=len(items))


@router.get("/unread-count")
async def unread_count(
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)
    count = await svc.get_unread_count(employee_id=current_user.id)
    return {"unread_count": count}


# ── Mark-read routes ───────────────────────────────────────────────────────────

@router.put("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)
    updated = await svc.mark_all_as_read(employee_id=current_user.id)
    return {"marked_read": updated}


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_one_read(
    notification_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)
    updated = await svc.mark_as_read(
        notification_id=notification_id,
        employee_id=current_user.id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    return updated


# ── Send routes (admin) ────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def send_custom_notification(
    payload: NotificationCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)
    created = await svc.create_bulk_notifications(
        employee_ids=[str(eid) for eid in payload.employee_ids],
        title=payload.title,
        message=payload.message,
        type=payload.type,
    )
    return {"created": len(created), "notifications": created}


@router.post(
    "/announcements",
    status_code=status.HTTP_201_CREATED,
    response_model=AnnouncementResponse,
)
async def send_announcement(
    payload: AnnouncementCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    svc: NotificationService = Depends(get_notification_service),
):
    _assert_valid_user_id(current_user.id)

    if not payload.employee_ids and not payload.department_ids:
        # No targeting — broadcast to all active employees
        recipient_ids = await svc.get_all_active_employee_ids()
        if not recipient_ids:
            raise HTTPException(status_code=404, detail="No active employees found.")
    else:
        # Resolve each source independently, then merge (union, no duplicates)
        id_set: set[str] = set()

        if payload.department_ids:
            dept_ids = await svc.get_active_employee_ids_by_department(payload.department_ids)
            if not dept_ids:
                raise HTTPException(
                    status_code=404,
                    detail="No active employees found in the specified department(s).",
                )
            id_set.update(dept_ids)

        if payload.employee_ids:
            id_set.update(str(eid) for eid in payload.employee_ids)

        recipient_ids = list(id_set)

    await svc.create_bulk_notifications(
        employee_ids=recipient_ids,
        title=payload.title,
        message=payload.message,
        type=NotificationType.ANNOUNCEMENT,
    )

    return AnnouncementResponse(
        created=len(recipient_ids),
        recipient_count=len(recipient_ids),
        title=payload.title,
        message=payload.message,
    )