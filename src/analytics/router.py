"""Router for the dashboard analytics endpoints."""
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.common.dependencies import CurrentUser, check_route_permission
from src.analytics.schemas import (
    RecentReview,
    LeaderboardEntry,
    PlatformStats,
    TeamReport,
    TeamSummary,
    ParticipationOverview,
    RecognitionTrend,
    PaginatedUserRecognition,
    PaginatedTeamRecognition,
)
from src.analytics.service import (
    get_recent_reviews_list,
    get_leaderboard_list,
    get_platform_stats,
    get_teams_summary,
    get_team_report,
    get_participation_overview,
    get_recognition_trend,
    get_recognition_users,
    get_recognition_teams,
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


# ══════════════════════════════════════════════════════════════
#  Participation Overview  (HR_ADMIN / SUPER_ADMIN only)
# ══════════════════════════════════════════════════════════════

@router.get(
    "/participation",
    response_model=ParticipationOverview,
    summary="Participation Overview",
    description=(
        "Returns pie-chart slices, key stats cards, and per-department "
        "participation rates. SUPER_ADMIN / HR_ADMIN only."
    ),
)
async def participation_overview(current_user: CurrentUser = _auth):
    """Return participation breakdown for the admin overview tab."""
    return await get_participation_overview()


# ══════════════════════════════════════════════════════════════
#  Recognition Trend  (HR_ADMIN / SUPER_ADMIN only)
# ══════════════════════════════════════════════════════════════

@router.get(
    "/recognition-trend",
    response_model=RecognitionTrend,
    summary="Recognition Trend",
    description=(
        "Returns time-series review activity. "
        "range=3m → 12 weekly buckets; range=6m → 6 monthly; range=1y → 12 monthly. "
        "SUPER_ADMIN / HR_ADMIN only."
    ),
)
async def recognition_trend(
    range: Literal["3m", "6m", "1y"] = Query("6m", description="Time range: 3m | 6m | 1y"),
    current_user: CurrentUser = _auth,
):
    return await get_recognition_trend(range_=range)


# ══════════════════════════════════════════════════════════════
#  Recognition — Per User  (HR_ADMIN / SUPER_ADMIN only)
# ══════════════════════════════════════════════════════════════

@router.get(
    "/recognition/users",
    response_model=PaginatedUserRecognition,
    summary="Recognition — Per User",
    description=(
        "Paginated list of employees with given/received review counts for the period. "
        "Sorted by given descending. "
        "range: week | month | quarter | year. SUPER_ADMIN / HR_ADMIN only."
    ),
)
async def recognition_users(
    range: Literal["week", "month", "quarter", "year"] = Query("month", description="week | month | quarter | year"),
    page:  int = Query(1,  ge=1,   description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: CurrentUser = _auth,
):
    return await get_recognition_users(range_=range, page=page, limit=limit)


# ══════════════════════════════════════════════════════════════
#  Recognition — Per Team  (HR_ADMIN / SUPER_ADMIN only)
# ══════════════════════════════════════════════════════════════

@router.get(
    "/recognition/teams",
    response_model=PaginatedTeamRecognition,
    summary="Recognition — Per Team",
    description=(
        "Paginated list of departments with aggregated given/received review counts and headcount. "
        "Sorted by given descending. "
        "range: week | month | quarter | year. SUPER_ADMIN / HR_ADMIN only."
    ),
)
async def recognition_teams(
    range: Literal["week", "month", "quarter", "year"] = Query("month", description="week | month | quarter | year"),
    page:  int = Query(1,  ge=1,   description="Page number (1-indexed)"),
    limit: int = Query(10, ge=1, le=50,  description="Items per page"),
    current_user: CurrentUser = _auth,
):
    return await get_recognition_teams(range_=range, page=page, limit=limit)