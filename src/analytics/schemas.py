

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime



class RecentReview(BaseModel):
    """A single review received by the employee.

    The list is sorted by ``review_at`` descending and capped at 5 items.

    Attributes:
        review_id: Unique UUID of the review record.
        reviewer_name: Username of the person who submitted the review.
            Falls back to ``"Unknown"`` if the reviewer relation is missing.
        rating: Numeric rating (typically 1–5).
        comment: Free‑text feedback from the reviewer.
        review_at: Timestamp when the review was created.
    """

    review_id: UUID
    reviewer_name: str
    rating: int
    comment: str
    review_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeaderboardEntry(BaseModel):
    """A single row in the points leaderboard.

    Employees are ranked by ``total_earned_points`` in descending order.
    The top 10 are returned by default.

    Attributes:
        rank: 1‑based position on the leaderboard.
        employee_id: UUID of the employee.
        username: Display name of the employee.
        department: Department the employee belongs to.
        total_earned_points: Cumulative points earned across all time.
    """

    rank: int
    employee_id: UUID
    username: str
    department: str
    total_earned_points: int

    model_config = ConfigDict(from_attributes=True)


class MetricWithGrowth(BaseModel):
    """A numeric KPI paired with this month vs last month values.

    Attributes:
        value: The lifetime or current total count/amount.
        this_month: Value for the current month.
        last_month: Value for the previous month.

    Example::

        {"value": 3000, "this_month": 500, "last_month": 400}
    """

    value: int = Field(0, description="Lifetime / current total value")
    this_month: int = Field(0, description="Value for the current month")
    last_month: int = Field(0, description="Value for the previous month")


class PlatformStats(BaseModel):
    """Platform‑wide statistics with month‑over‑month growth.

    Attributes:
        total_points: The authenticated user's lifetime wallet points.
            Growth is calculated from credit transactions this month vs last.
        rewards_redeemed: All‑time count of ``reward_history`` records.
            Growth compares this month's redemptions to last month's.
        reviews_received: All‑time count of reviews across the platform.
            Growth compares this month's reviews to last month's.
        active_users: Current count of employees with ACTIVE status.
            Growth compares against employees who existed before this month.
    """

    total_points: MetricWithGrowth
    rewards_redeemed: MetricWithGrowth
    reviews_received: MetricWithGrowth
    active_users: MetricWithGrowth



