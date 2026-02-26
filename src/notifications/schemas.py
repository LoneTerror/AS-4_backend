# src/notifications/schemas.py

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, UUID4


class NotificationType(str, Enum):
    REVIEW = "REVIEW"
    REWARD = "REWARD"
    SYSTEM = "SYSTEM"
    CELEBRATION = "CELEBRATION"


class CelebrationType(str, Enum):
    BIRTHDAY = "BIRTHDAY"
    WORK_ANNIVERSARY = "WORK_ANNIVERSARY"


# ── Responses ──────────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    notification_id: UUID4
    employee_id: UUID4
    title: str
    message: str
    type: NotificationType
    is_read: bool
    email_sent: bool
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int