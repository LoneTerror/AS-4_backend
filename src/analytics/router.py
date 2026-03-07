"""Router for the dashboard analytics endpoints."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from src.common.dependencies import CurrentUser, check_route_permission
from src.analytics.schemas import (
    RecentReview,
    LeaderboardEntry,
    PlatformStats,
    TeamReport,
    TeamSummary,
)
from src.analytics.service import (
    get_recent_reviews_list,
    get_leaderboard_list,
    get_platform_stats,
    get_teams_summary,
    get_team_report,
)

router = APIRouter()

_auth = Depends(check_route_permission)


# ══════════════════════════════════════════════════════════════
#  Existing routes
# ══════════════════════════════════════════════════════════════

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
    description="Get platform KPIs with month-over-month growth for the authenticated user",
)
async def platform_stats(current_user: CurrentUser = _auth):
    """Return four KPIs (total_points, rewards_redeemed, reviews_received, active_users)."""
    return await get_platform_stats(current_user.id)


# ══════════════════════════════════════════════════════════════
#  Admin — Team Report routes  (HR_ADMIN / SUPER_ADMIN only)
# ══════════════════════════════════════════════════════════════

@router.get(
    "/teams",
    response_model=List[TeamSummary],
    summary="All Teams Summary",
    description=(
        "Returns a summary card for every department. "
        "Accessible by HR_ADMIN and SUPER_ADMIN only."
    ),
)
async def list_teams(current_user: CurrentUser = _auth):
    """Return lightweight summary cards for all departments."""
    return await get_teams_summary()


@router.get(
    "/teams/{department_id}",
    response_model=TeamReport,
    summary="Team Detail Report",
    description=(
        "Returns a full report for one department, including per-member "
        "stats and performance scores. HR_ADMIN / SUPER_ADMIN only."
    ),
)
async def team_detail(department_id: str, current_user: CurrentUser = _auth):
    """Return full team report with member breakdown ordered by performance score."""
    report = await get_team_report(department_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Department '{department_id}' not found",
        )
    return report