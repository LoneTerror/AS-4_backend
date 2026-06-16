"""
src/analytics/service.py
─────────────────────────
Analytics Service — owns ZERO tables.

All direct Prisma queries against foreign-domain tables have been
replaced with calls to src/common/internal_client.py, which makes
HTTP requests to the owning service's /internal endpoints.

Data flow
─────────
  Analytics asks Wallet     → /internal/wallets/stats/batch, /leaderboard
  Analytics asks Review     → /internal/reviews/recent, /stats/batch, /trend,
                               /by-user, /by-team, /participation
  Analytics asks Employees  → /internal/employees/active-count,
                               /internal/employees/departments-with-members
"""
from __future__ import annotations

import logging
from typing import List

from src.analytics.schemas import (
    LeaderboardEntry,
    MetricWithGrowth,
    PaginatedTeamRecognition,
    PaginatedUserRecognition,
    ParticipationOverview,
    PlatformStats,
    RecentReview,
    RecognitionTrend,
    TeamReport,
    TeamSummary,
    TeamMemberReport,
)
from src.common import internal_client as svc
from src.common.cache import (
    L1_SHORT,
    L1_VOLATILE,
    TTL_SHORT,
    TTL_VOLATILE,
    cache_delete,
    cache_get,
    cache_set,
    invalidate_pattern,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Cache-key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _key_reviews(employee_id: str)  -> str: return f"dashboard:reviews:{employee_id}"
def _key_leaderboard()              -> str: return "dashboard:leaderboard"
def _key_platform(employee_id: str) -> str: return f"dashboard:platform:{employee_id}"
def _key_teams()                    -> str: return "dashboard:teams"
def _key_team(dept_id: str)         -> str: return f"dashboard:team:{dept_id}"


async def invalidate_reviews(employee_id: str) -> None:
    await cache_delete(_key_reviews(employee_id))
    await cache_delete(_key_platform(employee_id))

async def invalidate_leaderboard() -> None:
    await cache_delete(_key_leaderboard())

async def invalidate_teams() -> None:
    await cache_delete(_key_teams())
    await invalidate_pattern("dashboard:team:*")


# ─────────────────────────────────────────────────────────────────────────────
# Recent reviews  — VOLATILE (60s / 30s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recent_reviews_list(employee_id: str) -> List[RecentReview]:
    key    = _key_reviews(employee_id)
    cached = await cache_get(key, l1_ttl=L1_VOLATILE)
    if cached is not None:
        return [RecentReview(**r) for r in cached]

    raw = await svc.get_recent_reviews(employee_id, limit=5)
    out = [
        RecentReview(
            review_id=r["review_id"],
            reviewer_name=r.get("reviewer_name", "Unknown"),
            tags=r.get("category_codes") or [t.get("category_code", "") for t in r.get("category_tags", [])],
            comment=r["comment"],
            review_at=r["review_at"],
        )
        for r in raw
    ]

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_leaderboard_list() -> List[LeaderboardEntry]:
    key    = _key_leaderboard()
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return [LeaderboardEntry(**e) for e in cached]

    raw = await svc.get_leaderboard_data(limit=10)
    out = [LeaderboardEntry(**row) for row in raw]

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Platform stats  — VOLATILE (60s / 30s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_platform_stats(employee_id: str) -> PlatformStats:
    key    = _key_platform(employee_id)
    cached = await cache_get(key, l1_ttl=L1_VOLATILE)
    if cached is not None:
        return PlatformStats(**cached)

    import asyncio
    wallet_stats, review_stats, active_counts = await asyncio.gather(
        svc.get_wallet_stats(employee_id),
        svc.get_review_stats(employee_id),
        svc.get_active_users_count(),
    )

    result = PlatformStats(
        total_points=MetricWithGrowth(
            value=wallet_stats.get("total_earned_points", 0),
            this_month=wallet_stats.get("pts_this_month", 0),
            last_month=wallet_stats.get("pts_last_month", 0),
        ),
        rewards_redeemed=MetricWithGrowth(
            value=wallet_stats.get("rewards_total", 0),
            this_month=wallet_stats.get("rewards_this_month", 0),
            last_month=wallet_stats.get("rewards_last_month", 0),
        ),
        reviews_received=MetricWithGrowth(
            value=review_stats.get("reviews_total", 0),
            this_month=review_stats.get("reviews_this_month", 0),
            last_month=review_stats.get("reviews_last_month", 0),
        ),
        active_users=MetricWithGrowth(
            value=active_counts.get("now", 0),
            this_month=active_counts.get("now", 0),
            last_month=active_counts.get("last_month", 0),
        ),
    )

    await cache_set(key, result.model_dump(), ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Admin — Team Reports  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_teams_summary() -> List[TeamSummary]:
    key    = _key_teams()
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return [TeamSummary(**t) for t in cached]

    departments_data = await svc.get_departments_with_members()

    # Collect ALL employee IDs across every department in one pass,
    # then fetch wallet + review stats in exactly 2 HTTP calls total.
    all_emp_ids = [
        m["employee_id"]
        for dept in departments_data
        for m in dept.get("members", [])
    ]

    import asyncio
    wallet_map, review_map = await asyncio.gather(
        svc.get_wallet_stats_batch(all_emp_ids),
        svc.get_review_stats_batch(all_emp_ids),
    )

    out = []
    for dept in departments_data:
        report = _build_team_report_from_maps(dept, wallet_map, review_map)
        out.append(TeamSummary(
            department_id=dept["department_id"],
            department_name=dept["department_name"],
            total_members=report.total_members,
            total_points=report.total_points,
            avg_performance_score=report.avg_performance_score,
        ))

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return out


async def get_team_report(department_id: str) -> TeamReport | None:
    key    = _key_team(department_id)
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return TeamReport(**cached)

    departments_data = await svc.get_departments_with_members()
    dept = next(
        (d for d in departments_data if d["department_id"] == department_id),
        None,
    )
    if dept is None:
        return None

    emp_ids = [m["employee_id"] for m in dept.get("members", [])]

    import asyncio
    wallet_map, review_map = await asyncio.gather(
        svc.get_wallet_stats_batch(emp_ids),
        svc.get_review_stats_batch(emp_ids),
    )

    report = _build_team_report_from_maps(dept, wallet_map, review_map)
    await cache_set(key, report.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return report


def _build_team_report_from_maps(
    dept: dict,
    wallet_map: dict,
    review_map: dict,
) -> TeamReport:
    """
    Build a TeamReport for one department using pre-fetched batch maps.

    wallet_map and review_map are keyed by employee_id and come from the
    wallet/recognition batch endpoints. This function is pure — no I/O.
    """
    members_info = dept.get("members", [])

    if not members_info:
        return TeamReport(
            department_id=dept["department_id"],
            department_name=dept["department_name"],
            total_members=0, total_points=0, total_reviews=0,
            total_rewards=0, avg_performance_score=0.0, members=[],
        )

    members_raw = []
    for m in members_info:
        eid      = m["employee_id"]
        wallet_s = wallet_map.get(eid, {})
        review_s = review_map.get(eid, {})
        members_raw.append({
            "employee_id":         eid,
            "username":            m["username"],
            "designation":         m["designation_name"],
            "total_earned_points": wallet_s.get("total_earned_points", 0),
            "available_points":    wallet_s.get("available_points", 0),
            "reviews_received":    review_s.get("reviews_total", 0),
            "rewards_redeemed":    wallet_s.get("rewards_total", 0),
            "reviews_this_month":  review_s.get("reviews_this_month", 0),
            "points_this_month":   wallet_s.get("pts_this_month", 0),
        })

    # Performance score: 70% normalised points + 30% normalised reviews
    max_pts = max(m["total_earned_points"] for m in members_raw) or 1
    max_rev = max(m["reviews_received"]    for m in members_raw) or 1
    members_scored = [
        TeamMemberReport(
            **m,
            performance_score=round(
                (0.70 * m["total_earned_points"] / max_pts
                 + 0.30 * m["reviews_received"]  / max_rev) * 100,
                1,
            ),
        )
        for m in members_raw
    ]
    members_scored.sort(key=lambda x: x.performance_score, reverse=True)

    total_points  = sum(m["total_earned_points"] for m in members_raw)
    total_reviews = sum(m["reviews_received"]    for m in members_raw)
    total_rewards = sum(m["rewards_redeemed"]    for m in members_raw)
    avg_score     = round(
        sum(m.performance_score for m in members_scored) / len(members_scored), 1
    )

    return TeamReport(
        department_id=dept["department_id"],
        department_name=dept["department_name"],
        total_members=len(members_info),
        total_points=total_points,
        total_reviews=total_reviews,
        total_rewards=total_rewards,
        avg_performance_score=avg_score,
        members=members_scored,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Participation Overview  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_participation_overview() -> ParticipationOverview:
    key    = "dashboard:participation"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return ParticipationOverview(**cached)

    data   = await svc.get_participation_overview()
    result = ParticipationOverview(**data)

    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition Trend  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_trend(range_: str) -> RecognitionTrend:
    key    = f"dashboard:trend:{range_}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return RecognitionTrend(**cached)

    data   = await svc.get_recognition_trend(range_)
    result = RecognitionTrend(**data)

    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition per User  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_users(range_: str, page: int, limit: int) -> PaginatedUserRecognition:
    key    = f"dashboard:recognition_users:{range_}:{page}:{limit}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return PaginatedUserRecognition(**cached)

    data   = await svc.get_recognition_by_user(range_, page, limit)
    result = PaginatedUserRecognition(**data)

    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition per Team  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_teams(range_: str, page: int, limit: int) -> PaginatedTeamRecognition:
    key    = f"dashboard:recognition_teams:{range_}:{page}:{limit}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return PaginatedTeamRecognition(**cached)

    data   = await svc.get_recognition_by_team(range_, page, limit)
    result = PaginatedTeamRecognition(**data)

    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result