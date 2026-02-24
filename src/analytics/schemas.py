"""Pydantic response models for the ``GET /v1/dashboard/summary`` endpoint.

This module defines the complete response schema for the dashboard
summary API. Each model maps to a logical section of the response.

Models:
    EmployeeSummary: Authenticated employee's profile.
    RecentReview: A single review received by the employee.
    LeaderboardEntry: One row in the top‑N leaderboard.
    MetricWithGrowth: A numeric KPI with month‑over‑month growth.
    PlatformStats: Collection of platform‑wide KPIs.
    DashboardSummaryResponse: Top‑level response returned by the endpoint.
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID
from datetime import datetime


class EmployeeSummary(BaseModel):
    """Profile snapshot for the authenticated employee.

    Attributes:
        employee_id: Unique UUID of the employee.
        username: Display name (e.g. ``john.doe``).
        designation: Job title resolved from the ``designations`` table.
            Falls back to ``"N/A"`` when the relation is missing.
        department: Department name resolved from the ``departments`` table.
            Falls back to ``"N/A"`` when the relation is missing.
    """

    employee_id: UUID
    username: str
    designation: str
    department: str

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


class MetricWithGrowth(BaseModel):
    """A numeric KPI paired with its month‑over‑month growth rate.

    Attributes:
        value: The lifetime or current total count/amount.
        growth_percent: Percentage change compared to the previous month.
            Positive values indicate growth, negative values indicate decline.
            If last month was 0 and this month is > 0, growth is ``100.0``.
            If both months are 0, growth is ``0.0``.

    Example::

        {"value": 3000, "growth_percent": 25.0}
    """

    value: int = Field(0, description="Lifetime / current total value")
    growth_percent: float = Field(
        0.0,
        description="Percent change vs. last month (positive = increase)"
    )


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


class DashboardSummaryResponse(BaseModel):
    """Top‑level response for ``GET /v1/dashboard/summary``.

    Attributes:
        employee: Profile snapshot of the authenticated employee.
        recent_reviews: Up to 5 most recent reviews received, newest first.
        leaderboard: Top 10 employees ranked by total earned points.
        platform_stats: Four KPIs (total_points, rewards_redeemed,
            reviews_received, active_users), each with a lifetime value
            and a month‑over‑month growth percentage.
    """

    employee: EmployeeSummary
    recent_reviews: List[RecentReview] = []
    leaderboard: List[LeaderboardEntry] = []
    platform_stats: PlatformStats
