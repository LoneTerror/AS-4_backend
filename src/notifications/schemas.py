from datetime import datetime
from enum import Enum
from typing import Optional, List, Any

from pydantic import BaseModel, UUID4, field_validator


class NotificationType(str, Enum):
    REVIEW = "REVIEW"
    REWARD = "REWARD"
    REWARD_REDEEMED = "REWARD_REDEEMED"
    POINTS_CREDIT = "POINTS_CREDIT"
    SYSTEM = "SYSTEM"
    CELEBRATION = "CELEBRATION"
    ANNOUNCEMENT = "ANNOUNCEMENT"

class CelebrationType(str, Enum):
    BIRTHDAY         = "BIRTHDAY"
    WORK_ANNIVERSARY = "WORK_ANNIVERSARY"


# ── Requests ───────────────────────────────────────────────────────────────────

class NotificationCreateRequest(BaseModel):
    """
    Send a notification to one or more specific employees.

    Valid types for manual sends: REVIEW, REWARD, SYSTEM.
    - CELEBRATION is managed exclusively by the celebration worker.
    - ANNOUNCEMENT has its own dedicated endpoint (/announcements).
    - REWARD_REDEEMED and POINTS_CREDIT are legacy-only; they cannot be created.
    """
    employee_ids: List[UUID4]
    title: str
    message: str
    type: NotificationType = NotificationType.SYSTEM

    @field_validator("type")
    @classmethod
    def restrict_manual_types(cls, v: NotificationType) -> NotificationType:
        _RESERVED = {
            NotificationType.CELEBRATION,
            NotificationType.ANNOUNCEMENT,
            # Prevent accidental re-creation of legacy types
            NotificationType.REWARD_REDEEMED,
            NotificationType.POINTS_CREDIT,
        }
        if v in _RESERVED:
            raise ValueError(
                f"Type '{v.value}' cannot be sent via this endpoint. "
                "Use POST /notifications/announcements for ANNOUNCEMENT, "
                "or let the celebration worker handle CELEBRATION."
            )
        return v


class AnnouncementCreateRequest(BaseModel):
    """
    Blast a notification to ALL active employees at once.
    Optionally restrict to specific department(s) or employee IDs.
    If both are omitted, every active employee receives it.
    """
    title: str
    message: str
    # Optional targeting — if both are None, broadcast to everyone
    department_ids: Optional[List[UUID4]] = None
    employee_ids:   Optional[List[UUID4]] = None


# ── Responses ──────────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    notification_id: UUID4
    employee_id:     UUID4
    title:           str
    message:         str
    type:            NotificationType
    is_read:         bool
    email_sent:      bool
    created_at:      datetime
    read_at:         Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_validator("type", mode="before")
    @classmethod
    def coerce_legacy_type(cls, v: Any) -> Any:
        """
        Secondary safety net: if a legacy type value reaches the serialiser
        despite the DB-level filter in service.py, remap it to SYSTEM rather
        than crashing with a 500.

        Known legacy types:
          - REWARD_REDEEMED, POINTS_CREDIT — first-generation legacy
          - BONUS, CREDIT — older pre-enum values found in DB

        The primary defence is the `type: {not: {in: _LEGACY_TYPES}}` filter
        in get_notifications() and get_unread_count(). This validator is a
        fallback for any query path that doesn't apply that filter.
        """
        _LEGACY_REMAP = {"REWARD_REDEEMED", "POINTS_CREDIT", "BONUS", "CREDIT"}
        if isinstance(v, str) and v in _LEGACY_REMAP:
            return "SYSTEM"
        return v


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    total: int


class AnnouncementResponse(BaseModel):
    """Returned after a successful announcement blast."""
    created:          int
    recipient_count:  int
    title:            str
    message:          str