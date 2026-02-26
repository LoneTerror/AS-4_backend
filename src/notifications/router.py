from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from prisma import Prisma

from src.employees.dependencies import get_current_employee, get_db
from .schemas import NotificationListResponse, NotificationResponse
from .service import NotificationService

router = APIRouter(prefix="/v1/notifications", tags=["Notifications"])


def get_notification_service(db: Prisma = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


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