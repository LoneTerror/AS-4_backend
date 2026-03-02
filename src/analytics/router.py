"""Router for the dashboard analytics endpoints."""
from typing import List

from fastapi import APIRouter, Depends

from src.analytics.dependencies import CurrentUser, require_roles
from src.analytics.schemas import (
    RecentReview,
    LeaderboardEntry,
    PlatformStats,
)
from src.analytics.service import (
    get_recent_reviews_list,
    get_leaderboard_list,
    get_platform_stats,
)

router = APIRouter()

_auth = Depends(require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"))




@router.get(
    "/recent-reviews",
    response_model=List[RecentReview],
    summary="Recent Reviews",
    description="Get the last 5 reviews received by the authenticated employee",
)
async def recent_reviews(current_user: CurrentUser = _auth):
    """Return up to 5 most recent reviews received, newest first."""
    return await get_recent_reviews_list(current_user.id)


@router.get(
    "/leaderboard",
    response_model=List[LeaderboardEntry],
    summary="Leaderboard",
    description="Get the top 10 employees ranked by total earned points",
)
async def leaderboard(current_user: CurrentUser = _auth):
    """Return the top 10 employees ranked by total earned points."""
    return await get_leaderboard_list()


@router.get(
    "/platform-stats",
    response_model=PlatformStats,
    summary="Platform Stats",
    description="Get platform KPIs with month-over-month growth for the authenticated users",
)
async def platform_stats(current_user: CurrentUser = _auth):
    """Return four KPIs (total_points, rewards_redeemed, reviews_received, active_users)."""
    return await get_platform_stats(current_user.id)
