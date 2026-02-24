from fastapi import APIRouter, Depends, Query, HTTPException, status
from src.auth.dependencies import get_current_user, require_roles
from .schemas import NotificationListResponse, NotificationResponse, NotificationCreate
from .service import NotificationService

router = APIRouter()

@router.get("/", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user = Depends(get_current_user)
):
    """Returns paginated notifications for the authenticated employee"""
    items, total = await NotificationService.get_user_notifications(current_user.id, page, limit)
    
    return {
        "data": items,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": limit,
            "total_pages": (total + limit - 1) // limit
        }
    }

@router.patch("/{id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(id: str, current_user = Depends(get_current_user)):
    """Updates status of a specific notification to read"""
    updated = await NotificationService.mark_as_read(id, current_user.id)
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found")
    return None

@router.post("/send", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
async def system_send_notification(
    payload: NotificationCreate,
    _ = Depends(require_roles("SUPER_ADMIN", "SYSTEM_SERVICE"))
):
    """Internal API for other microservices to trigger notifications"""
    return await NotificationService.create_notification(payload)