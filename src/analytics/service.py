"""Service layer for the dashboard summary endpoint."""
from fastapi import HTTPException, status

from src.analytics.queries import (
    get_employee_with_details,
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


def _growth_percent(this_month: int, last_month: int) -> float:
    """Calculate month-over-month growth percentage."""
    if last_month == 0:
        return 100.0 if this_month > 0 else 0.0
    return round(((this_month - last_month) / last_month) * 100, 1)


async def get_dashboard_summary(employee_id: str) -> dict:
    """
    Build the personalized dashboard summary.

    Returns:
    - employee: profile info
    - recent_reviews: last 5 reviews received
    - leaderboard: top 10 by points
    - platform_stats:
      - total_points: user's lifetime points + MoM growth
      - rewards_redeemed: lifetime count + MoM growth
      - reviews_received: lifetime count + MoM growth
      - active_users: current count + MoM growth
    """

    # 1. Employee profile
    employee = await get_employee_with_details(employee_id)
    if not employee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Employee not found"
        )

    designation = employee.designations_employees_designation_idTodesignations
    department = employee.departments_employees_department_idTodepartments

    employee_summary = {
        "employee_id": employee.employee_id,
        "username": employee.username,
        "designation": designation.designation_name if designation else "N/A",
        "department": department.department_name if department else "N/A",
    }

    # 2. Recent reviews received
    raw_reviews = await get_recent_reviews(employee_id, limit=5)
    recent_reviews = []
    for review in raw_reviews:
        reviewer = review.employees_reviews_reviewer_idToemployees
        recent_reviews.append({
            "review_id": review.review_id,
            "reviewer_name": reviewer.username if reviewer else "Unknown",
            "rating": review.rating,
            "comment": review.comment,
            "review_at": review.review_at,
        })

    # 3. Leaderboard
    raw_leaderboard = await get_leaderboard(limit=10)
    leaderboard = []
    for rank, w in enumerate(raw_leaderboard, start=1):
        emp = w.employees_wallets_employee_idToemployees
        dept = emp.departments_employees_department_idTodepartments if emp else None
        leaderboard.append({
            "rank": rank,
            "employee_id": emp.employee_id if emp else w.employee_id,
            "username": emp.username if emp else "Unknown",
            "department": dept.department_name if dept else "N/A",
            "total_earned_points": w.total_earned_points,
        })

    # 4. Platform stats
    # 4a. Total points (user's wallet total + MoM growth of earned points)
    user_points = await get_user_total_points(employee_id)
    pts_this = await get_user_points_earned_this_month(employee_id)
    pts_last = await get_user_points_earned_last_month(employee_id)

    # 4b. Rewards redeemed (user's lifetime + MoM)
    rewards_total = await get_user_total_rewards_redeemed(employee_id)
    rewards_this = await get_user_rewards_redeemed_this_month(employee_id)
    rewards_last = await get_user_rewards_redeemed_last_month(employee_id)

    # 4c. Reviews received (user's lifetime + MoM)
    reviews_total = await get_user_total_reviews(employee_id)
    reviews_this = await get_user_reviews_this_month(employee_id)
    reviews_last = await get_user_reviews_last_month(employee_id)

    # 4d. Active users (current + MoM)
    active_now = await get_active_users_count()
    active_last = await get_active_users_count_last_month()

    platform_stats = {
        "total_points": {
            "value": user_points,
            "growth_percent": _growth_percent(pts_this, pts_last),
        },
        "rewards_redeemed": {
            "value": rewards_total,
            "growth_percent": _growth_percent(rewards_this, rewards_last),
        },
        "reviews_received": {
            "value": reviews_total,
            "growth_percent": _growth_percent(reviews_this, reviews_last),
        },
        "active_users": {
            "value": active_now,
            "growth_percent": _growth_percent(active_now, active_last),
        },
    }

    return {
        "employee": employee_summary,
        "recent_reviews": recent_reviews,
        "leaderboard": leaderboard,
        "platform_stats": platform_stats,
    }
