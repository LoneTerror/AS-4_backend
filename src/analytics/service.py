"""Service layer for the dashboard analytics endpoints — with Redis caching."""
import asyncio
import logging
import traceback
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
    get_all_departments,
    get_department_by_id,
    get_employees_in_department,
    get_wallet_for_employee,
    get_credit_type_ids,
    get_points_this_month_for_wallet,
    get_review_count_for_employee,
    get_reviews_this_month_for_employee,
    get_rewards_redeemed_for_wallet,
)
from src.analytics.schemas import (
    RecentReview,
    LeaderboardEntry,
    MetricWithGrowth,
    PlatformStats,
    TeamMemberReport,
    TeamReport,
    TeamSummary,
)
from src.common.cache import cache_get, cache_set, cache_delete, invalidate_pattern

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# TTLs (seconds)
# ─────────────────────────────────────────────────────────────────────────────
TTL_TEAMS        = 300   # 5 min  — heavy aggregation, changes rarely
TTL_PLATFORM     = 120   # 2 min  — counters, ok to be slightly stale
TTL_LEADERBOARD  = 300   # 5 min  — points rarely change mid-session
TTL_REVIEWS      = 60    # 1 min  — per-user, invalidated on new review

# ─────────────────────────────────────────────────────────────────────────────
# Cache-key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _key_reviews(employee_id: str)   -> str: return f"dashboard:reviews:{employee_id}"
def _key_leaderboard()               -> str: return "dashboard:leaderboard"
def _key_platform(employee_id: str)  -> str: return f"dashboard:platform:{employee_id}"
def _key_teams()                     -> str: return "dashboard:teams"
def _key_team(dept_id: str)          -> str: return f"dashboard:team:{dept_id}"


# ─────────────────────────────────────────────────────────────────────────────
# Public invalidation helpers  (called by other services after writes)
# ─────────────────────────────────────────────────────────────────────────────

async def invalidate_reviews(employee_id: str) -> None:
    """Call after a new review is submitted for *employee_id*."""
    await cache_delete(_key_reviews(employee_id))
    await cache_delete(_key_platform(employee_id))

async def invalidate_leaderboard() -> None:
    """Call after points are awarded / redeemed."""
    await cache_delete(_key_leaderboard())

async def invalidate_teams() -> None:
    """Call after department membership changes."""
    await cache_delete(_key_teams())
    await invalidate_pattern("dashboard:team:*")


# ─────────────────────────────────────────────────────────────────────────────
# Recent reviews
# ─────────────────────────────────────────────────────────────────────────────

async def get_recent_reviews_list(employee_id: str) -> List[RecentReview]:
    key = _key_reviews(employee_id)
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache HIT %s", key)
        return [RecentReview(**r) for r in cached]

    raw = await get_recent_reviews(employee_id, limit=5)
    out = []
    for r in raw:
        reviewer = r.employees_reviews_reviewer_idToemployees
        out.append(RecentReview(
            review_id=r.review_id,
            reviewer_name=reviewer.username if reviewer else "Unknown",
            rating=r.rating,
            comment=r.comment,
            review_at=r.review_at,
        ))

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_REVIEWS)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────────────────────────────────────

async def get_leaderboard_list() -> List[LeaderboardEntry]:
    key = _key_leaderboard()
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache HIT %s", key)
        return [LeaderboardEntry(**e) for e in cached]

    raw = await get_leaderboard(limit=10)
    out = []
    for rank, w in enumerate(raw, start=1):
        emp  = w.employees_wallets_employee_idToemployees
        dept = emp.departments_employees_department_idTodepartments if emp else None
        out.append(LeaderboardEntry(
            rank=rank,
            employee_id=emp.employee_id if emp else w.employee_id,
            username=emp.username if emp else "Unknown",
            department=dept.department_name if dept else "N/A",
            total_earned_points=w.total_earned_points,
        ))

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_LEADERBOARD)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Platform stats
# ─────────────────────────────────────────────────────────────────────────────

async def get_platform_stats(employee_id: str) -> PlatformStats:
    key = _key_platform(employee_id)
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache HIT %s", key)
        return PlatformStats(**cached)

    (
        user_points, pts_this, pts_last,
        rewards_total, rewards_this, rewards_last,
        reviews_total, reviews_this, reviews_last,
        active_now, active_last,
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

    result = PlatformStats(
        total_points    =MetricWithGrowth(value=user_points,    this_month=pts_this,     last_month=pts_last),
        rewards_redeemed=MetricWithGrowth(value=rewards_total,  this_month=rewards_this, last_month=rewards_last),
        reviews_received=MetricWithGrowth(value=reviews_total,  this_month=reviews_this, last_month=reviews_last),
        active_users    =MetricWithGrowth(value=active_now,     this_month=active_now,   last_month=active_last),
    )

    await cache_set(key, result.model_dump(), ttl=TTL_PLATFORM)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Admin — Team Reports
# ─────────────────────────────────────────────────────────────────────────────

def _compute_scores(members_raw: list) -> list:
    if not members_raw:
        return []
    max_pts = max(m["total_earned_points"] for m in members_raw) or 1
    max_rev = max(m["reviews_received"]    for m in members_raw) or 1
    return [
        {
            **m,
            "performance_score": round(
                (0.70 * m["total_earned_points"] / max_pts
                 + 0.30 * m["reviews_received"]  / max_rev) * 100,
                1,
            ),
        }
        for m in members_raw
    ]


async def _build_member(emp, credit_type_ids: list) -> dict:
    wallet = await get_wallet_for_employee(emp)

    if wallet:
        rewards, pts_month = await asyncio.gather(
            get_rewards_redeemed_for_wallet(wallet),
            get_points_this_month_for_wallet(wallet, credit_type_ids),
        )
        total_pts = wallet.total_earned_points
        avail_pts = wallet.available_points
    else:
        rewards = pts_month = total_pts = avail_pts = 0

    reviews_total, reviews_month = await asyncio.gather(
        get_review_count_for_employee(emp),
        get_reviews_this_month_for_employee(emp),
    )

    desig = getattr(emp, "designations_employees_designation_idTodesignations", None)

    return {
        "employee_id":         emp.employee_id,
        "username":            emp.username,
        "designation":         desig.designation_name if desig else "N/A",
        "total_earned_points": total_pts,
        "available_points":    avail_pts,
        "reviews_received":    reviews_total,
        "rewards_redeemed":    rewards,
        "reviews_this_month":  reviews_month,
        "points_this_month":   pts_month,
    }


async def _dept_members(dept) -> list:
    employees = await get_employees_in_department(dept)
    if not employees:
        return []
    credit_type_ids = await get_credit_type_ids()
    members_raw = await asyncio.gather(
        *[_build_member(emp, credit_type_ids) for emp in employees]
    )
    return _compute_scores(list(members_raw))


async def get_teams_summary() -> List[TeamSummary]:
    key = _key_teams()
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache HIT %s", key)
        return [TeamSummary(**s) for s in cached]

    departments = await get_all_departments()
    logger.info("[teams_summary] %d departments", len(departments))

    summaries: List[TeamSummary] = []
    for dept in departments:
        try:
            scored = await _dept_members(dept)
            logger.info("[teams_summary] %s → %d members", dept.department_name, len(scored))
        except Exception:
            logger.error(
                "[teams_summary] FAILED for dept=%s\n%s",
                dept.department_name, traceback.format_exc(),
            )
            scored = []

        summaries.append(
            TeamSummary(
                department_id=dept.department_id,
                department_name=dept.department_name,
                total_members=len(scored),
                total_points=sum(m["total_earned_points"] for m in scored),
                avg_performance_score=(
                    round(sum(m["performance_score"] for m in scored) / len(scored), 1)
                    if scored else 0.0
                ),
            )
        )

    await cache_set(key, [s.model_dump() for s in summaries], ttl=TTL_TEAMS)
    return summaries


async def get_team_report(department_id: str) -> TeamReport | None:
    key = _key_team(department_id)
    cached = await cache_get(key)
    if cached is not None:
        logger.debug("cache HIT %s", key)
        return TeamReport(**cached)

    dept = await get_department_by_id(department_id)
    if not dept:
        return None

    scored = await _dept_members(dept)

    if not scored:
        report = TeamReport(
            department_id=dept.department_id,
            department_name=dept.department_name,
            total_members=0,
            total_points=0,
            total_reviews=0,
            total_rewards=0,
            avg_performance_score=0.0,
            members=[],
        )
    else:
        scored.sort(key=lambda m: m["performance_score"], reverse=True)
        members = [TeamMemberReport(**m) for m in scored]
        report = TeamReport(
            department_id=dept.department_id,
            department_name=dept.department_name,
            total_members=len(members),
            total_points=sum(m.total_earned_points for m in members),
            total_reviews=sum(m.reviews_received   for m in members),
            total_rewards=sum(m.rewards_redeemed   for m in members),
            avg_performance_score=round(
                sum(m.performance_score for m in members) / len(members), 1
            ),
            members=members,
        )

    await cache_set(key, report.model_dump(), ttl=TTL_TEAMS)
    return report