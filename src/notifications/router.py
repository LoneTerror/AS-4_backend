from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prisma import Prisma

from src.employees.dependencies import get_current_employee, get_db
from .schemas import (
    AnnouncementCreateRequest,
    AnnouncementResponse,
    NotificationCreateRequest,
    NotificationListResponse,
    NotificationResponse,
    NotificationType,
)
from .service import NotificationService

router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])


def get_notification_service(db: Prisma = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


# ── Read routes ────────────────────────────────────────────────────────────────

@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=200),
    unread_only: bool = Query(default=False),
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    items = await svc.get_notifications(
        employee_id=current_employee.id,
        limit=limit,
        unread_only=unread_only,
    )
    return NotificationListResponse(
        notifications=items,
        total=len(items),
    )


@router.get("/unread-count")
async def unread_count(
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    count = await svc.get_unread_count(employee_id=current_employee.id)
    return {"unread_count": count}


# ── Mark-read routes ───────────────────────────────────────────────────────────

@router.put("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_read(
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    updated = await svc.mark_all_as_read(employee_id=current_employee.id)
    return {"marked_read": updated}


@router.put("/{notification_id}/read", response_model=NotificationResponse)
async def mark_one_read(
    notification_id: UUID,
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    updated = await svc.mark_as_read(
        notification_id=notification_id,
        employee_id=current_employee.id,
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
    # TODO: replace get_current_employee with an admin-guard dependency
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    """
    Send a custom notification to one or more specific employees.
    The email worker will pick these up automatically within its next poll cycle.

    Body example:
    {
        "employee_ids": ["uuid-1", "uuid-2"],
        "title": "Action required: Complete your self-review",
        "message": "Please submit your Q2 self-review by Friday.",
        "type": "SYSTEM"
    }
    """
    created = await svc.create_bulk_notifications(
        employee_ids=[str(eid) for eid in payload.employee_ids],
        title=payload.title,
        message=payload.message,
        type=payload.type,
    )
    return {
        "created": len(created),
        "notifications": created,
    }


@router.post("/announcements", status_code=status.HTTP_201_CREATED, response_model=AnnouncementResponse)
async def send_announcement(
    payload: AnnouncementCreateRequest,
    # TODO: replace get_current_employee with an admin-guard dependency
    current_employee=Depends(get_current_employee),
    svc: NotificationService = Depends(get_notification_service),
):
    """
    Blast a notification to employees company-wide, or target by department
    or a specific list of employee IDs.

    Priority:
      1. employee_ids  — if provided, send only to these employees
      2. department_ids — if provided, send to all active employees in those departments
      3. neither        — send to ALL active employees

    Body examples:

    # Company-wide
    {
        "title": "🎉 Q2 All-hands is this Friday",
        "message": "Join us at 3 PM in the main hall or via the Zoom link in your calendar."
    }

    # Department-targeted
    {
        "title": "Engineering offsite details",
        "message": "See the attached itinerary for next week's offsite.",
        "department_ids": ["uuid-dept-eng"]
    }

    # Specific employees
    {
        "title": "Reminder: pending approvals",
        "message": "You have pending review approvals. Please action them today.",
        "employee_ids": ["uuid-1", "uuid-2"]
    }
    """
    # Resolve the target recipient list
    if payload.employee_ids:
        recipient_ids = [str(eid) for eid in payload.employee_ids]
    elif payload.department_ids:
        recipient_ids = await svc.get_active_employee_ids_by_department(
            payload.department_ids
        )
        if not recipient_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active employees found in the specified department(s).",
            )
    else:
        recipient_ids = await svc.get_all_active_employee_ids()
        if not recipient_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active employees found.",
            )

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