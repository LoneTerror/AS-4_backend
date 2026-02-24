from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime

class NotificationBase(BaseModel):
    title: str = Field(..., example="Reward Credited")
    message: str = Field(..., example="You have received 500 points for Q3 performance.")
    recipient_id: UUID

class NotificationCreate(NotificationBase):
    """Used for inter-service communication to trigger a new notification"""
    priority: Optional[str] = "NORMAL"

class NotificationResponse(NotificationBase):
    notification_id: UUID
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int

class NotificationListResponse(BaseModel):
    data: List[NotificationResponse]
    pagination: PaginationMeta