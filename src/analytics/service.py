"""Service layer for the dashboard analytics endpoints."""
import asyncio
from typing import List


from src.analytics.queries import (
    get_recent_reviews,
    get_leaderboard,
    get_user_total_points,
    get_user_points_earned_this_month,
    get_user_points_earned_last_month,
    get_user_total_rewards_redeemed,
    get_user_rewards_redeemed_this_month,
    get_user_rewards_redeemed_last_month,
    get_user_total_reviews,
    get_user_reviews_this_month,
    get_user_reviews_last_month,
    get_active_users_count,
    get_active_users_count_last_month,
)
from src.analytics.schemas import (
    RecentReview,
    LeaderboardEntry,
    MetricWithGrowth,
    PlatformStats,
)



# ──────────────────────────────────────────────────────────────
#  2. Recent reviews received
# ──────────────────────────────────────────────────────────────

async def get_recent_reviews_list(employee_id: str) -> List[RecentReview]:
    """Return the last 5 reviews received by the employee."""
    raw_reviews = await get_recent_reviews(employee_id, limit=5)
    reviews: List[RecentReview] = []
    for review in raw_reviews:
        reviewer = review.employees_reviews_reviewer_idToemployees
        reviews.append(
            RecentReview(
                review_id=review.review_id,
                reviewer_name=reviewer.username if reviewer else "Unknown",
                rating=review.rating,
                comment=review.comment,
                review_at=review.review_at,
            )
        )
    return reviews


# ──────────────────────────────────────────────────────────────
#  3. Leaderboard
# ──────────────────────────────────────────────────────────────

async def get_leaderboard_list() -> List[LeaderboardEntry]:
    """Return the top 10 employees ranked by total earned points."""
    raw_leaderboard = await get_leaderboard(limit=10)
    leaderboard: List[LeaderboardEntry] = []
    for rank, w in enumerate(raw_leaderboard, start=1):
        emp = w.employees_wallets_employee_idToemployees
        dept = emp.departments_employees_department_idTodepartments if emp else None
        leaderboard.append(
            LeaderboardEntry(
                rank=rank,
                employee_id=emp.employee_id if emp else w.employee_id,
                username=emp.username if emp else "Unknown",
                department=dept.department_name if dept else "N/A",
                total_earned_points=w.total_earned_points,
            )
        )
    return leaderboard


# ──────────────────────────────────────────────────────────────
#  4. Platform stats
# ──────────────────────────────────────────────────────────────

async def get_platform_stats(employee_id: str) -> PlatformStats:
    """Build platform-wide KPIs with month-over-month growth."""

    (
        user_points,
        pts_this,
        pts_last,
        rewards_total,
        rewards_this,
        rewards_last,
        reviews_total,
        reviews_this,
        reviews_last,
        active_now,
        active_last,
    ) = await asyncio.gather(
        get_user_total_points(employee_id),
        get_user_points_earned_this_month(employee_id),
        get_user_points_earned_last_month(employee_id),
        get_user_total_rewards_redeemed(employee_id),
        get_user_rewards_redeemed_this_month(employee_id),
        get_user_rewards_redeemed_last_month(employee_id),
        get_user_total_reviews(employee_id),
        get_user_reviews_this_month(employee_id),
        get_user_reviews_last_month(employee_id),
        get_active_users_count(),
        get_active_users_count_last_month(),
    )

    return PlatformStats(
        total_points=MetricWithGrowth(
            value=user_points,
            this_month=pts_this,
            last_month=pts_last,
        ),
        rewards_redeemed=MetricWithGrowth(
            value=rewards_total,
            this_month=rewards_this,
            last_month=rewards_last,
        ),
        reviews_received=MetricWithGrowth(
            value=reviews_total,
            this_month=reviews_this,
            last_month=reviews_last,
        ),
        active_users=MetricWithGrowth(
            value=active_now,
            this_month=active_now,
            last_month=active_last,
        ),
    )
