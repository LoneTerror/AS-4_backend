"""Router for the dashboard summary endpoint."""
from fastapi import APIRouter, Depends

from src.analytics.dependencies import CurrentUser, require_roles
from src.analytics.schemas import DashboardSummaryResponse
from src.analytics.service import get_dashboard_summary

router = APIRouter()


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Dashboard Summary",
    description="Get personalized dashboard summary for the authenticated employee"
)
async def dashboard_summary(
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    )
):
    """Return the personalised dashboard summary for the authenticated user.

    The response contains:

    - **employee** — profile snapshot (name, designation, department).
    - **recent_reviews** — last 5 reviews received, newest first.
    - **leaderboard** — top 10 employees ranked by total earned points.
    - **platform_stats** — four KPIs, each with a lifetime ``value``
      and a ``growth_percent`` comparing this month to last month:
      ``total_points``, ``rewards_redeemed``, ``reviews_received``,
      ``active_users``.

    Raises:
        HTTPException 401: Missing or invalid bearer token.
        HTTPException 403: Authenticated user lacks the required role.
        HTTPException 404: Employee record not found in the database.
    """
    return await get_dashboard_summary(current_user.id)
