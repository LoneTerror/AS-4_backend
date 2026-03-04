from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, UUID4


# ── Sub-models ─────────────────────────────────────────────────────────────────

class TopPerformer(BaseModel):
    employee_id: UUID4
    username: str
    count: int


class WeeklyDigestData(BaseModel):
    week_start: datetime
    week_end: datetime
    total_recognitions: int
    total_points_awarded: float
    unique_givers: int
    unique_receivers: int
    top_giver: Optional[TopPerformer] = None
    top_receiver: Optional[TopPerformer] = None


# ── Request ────────────────────────────────────────────────────────────────────

class DigestEmailRequest(BaseModel):
    """
    Trigger a weekly digest email for a specific manager.
    week_start defaults to last Monday (UTC) if omitted.
    """
    manager_email: EmailStr
    week_start: Optional[datetime] = None


# ── Response ───────────────────────────────────────────────────────────────────

class DigestResponse(BaseModel):
    success: bool
    message: str
    data: Optional[WeeklyDigestData] = None