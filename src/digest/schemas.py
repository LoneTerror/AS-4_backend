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

    manager_id  — the employee UUID of the manager whose team to scope the
                  digest to. Only reviews where the receiver reports to this
                  manager (employees.manager_id == manager_id) are included.
                  When omitted the digest covers the whole platform.

    week_start  — defaults to last completed Monday (UTC) if omitted.
    """
    manager_email: EmailStr
    manager_id:    Optional[UUID4] = None
    week_start:    Optional[datetime] = None


# ── Response ───────────────────────────────────────────────────────────────────

class DigestResponse(BaseModel):
    success: bool
    message: str
    data: Optional[WeeklyDigestData] = None