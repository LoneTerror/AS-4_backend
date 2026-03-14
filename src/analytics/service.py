"""Service layer for the dashboard analytics endpoints — with Redis caching."""
import asyncio
import logging
import traceback
from typing import List

builtins_range = range  # alias before any function param named 'range' shadows the builtin

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
from datetime import datetime, timedelta, timezone
from src.common.cache import (
    cache_get, cache_set, cache_delete, invalidate_pattern,
    TTL_VOLATILE,  L1_VOLATILE,  # recent reviews, platform stats →  60s /  30s
    TTL_SHORT,     L1_SHORT,     # leaderboard, team reports     → 300s /  60s
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


# ─────────────────────────────────────────────────────────────────────────────
# Public invalidation helpers
# ─────────────────────────────────────────────────────────────────────────────

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
    logger.debug("cache reviews key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
        return [RecentReview(**r) for r in cached]

    raw = await get_recent_reviews(employee_id, limit=5)
    out = []
    for r in raw:
        reviewer = r.employees_reviews_reviewer_idToemployees
        out.append(RecentReview(
            review_id=r.review_id,
            reviewer_name=reviewer.username if reviewer else "Unknown",
            tags=[t.category_code_snapshot for t in (r.review_category_tags or [])],
            comment=r.comment,
            review_at=r.review_at,
        ))

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Leaderboard  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_leaderboard_list() -> List[LeaderboardEntry]:
    key    = _key_leaderboard()
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    logger.debug("cache leaderboard key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
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

    await cache_set(key, [o.model_dump() for o in out], ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Platform stats  — VOLATILE (60s / 30s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_platform_stats(employee_id: str) -> PlatformStats:
    key    = _key_platform(employee_id)
    cached = await cache_get(key, l1_ttl=L1_VOLATILE)
    logger.debug("cache platform key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
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
        total_points    =MetricWithGrowth(value=user_points,   this_month=pts_this,     last_month=pts_last),
        rewards_redeemed=MetricWithGrowth(value=rewards_total, this_month=rewards_this, last_month=rewards_last),
        reviews_received=MetricWithGrowth(value=reviews_total, this_month=reviews_this, last_month=reviews_last),
        active_users    =MetricWithGrowth(value=active_now,    this_month=active_now,   last_month=active_last),
    )

    await cache_set(key, result.model_dump(), ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Admin — Team Reports  — SHORT (300s / 60s)
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
    # Fetch wallet + both review counts in parallel — previously wallet was
    # fetched first (serial), then reviews. Now all 3 fire simultaneously.
    wallet, reviews_total, reviews_month = await asyncio.gather(
        get_wallet_for_employee(emp),
        get_review_count_for_employee(emp),
        get_reviews_this_month_for_employee(emp),
    )

    if wallet:
        rewards, pts_month = await asyncio.gather(
            get_rewards_redeemed_for_wallet(wallet),
            get_points_this_month_for_wallet(wallet, credit_type_ids),
        )
        total_pts = wallet.total_earned_points
        avail_pts = wallet.available_points
    else:
        rewards = pts_month = total_pts = avail_pts = 0

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


async def _dept_members(dept, credit_type_ids: list) -> list:
    # credit_type_ids passed in — fetched once at caller level, not per dept
    employees = await get_employees_in_department(dept)
    if not employees:
        return []
    members_raw = await asyncio.gather(
        *[_build_member(emp, credit_type_ids) for emp in employees]
    )
    return _compute_scores(list(members_raw))


async def get_teams_summary() -> List[TeamSummary]:
    key    = _key_teams()
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    logger.debug("cache teams key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
        return [TeamSummary(**s) for s in cached]

    departments = await get_all_departments()
    logger.info("[teams_summary] %d departments", len(departments))

    async def _safe_dept_members(dept, credit_type_ids):
        try:
            scored = await _dept_members(dept, credit_type_ids)
            logger.info("[teams_summary] %s → %d members", dept.department_name, len(scored))
            return dept, scored
        except Exception:
            logger.error(
                "[teams_summary] FAILED for dept=%s\n%s",
                dept.department_name, traceback.format_exc(),
            )
            return dept, []

    # All departments computed in parallel — was a sequential for-loop
    # Fetch credit_type_ids ONCE — not once per department
    credit_type_ids = await get_credit_type_ids()

    dept_results = await asyncio.gather(*[_safe_dept_members(d, credit_type_ids) for d in departments])

    summaries: List[TeamSummary] = []
    for dept, scored in dept_results:
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

    await cache_set(key, [s.model_dump() for s in summaries], ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return summaries


async def get_team_report(department_id: str) -> TeamReport | None:
    key    = _key_team(department_id)
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    logger.debug("cache team key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
        return TeamReport(**cached)

    dept = await get_department_by_id(department_id)
    if not dept:
        return None

    credit_type_ids = await get_credit_type_ids()
    scored = await _dept_members(dept, credit_type_ids)

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
        report  = TeamReport(
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

    await cache_set(key, report.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# Participation Overview  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_participation_overview():
    """
    Returns participation stats: who has given/received reviews,
    pie-chart slices, and per-department participation rates.
    """
    from src.analytics.schemas import ParticipationOverview
    import asyncio

    key    = "dashboard:participation"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    logger.debug("cache participation key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
        return ParticipationOverview(**cached)

    from src.analytics.schemas import ParticipationSlice, ParticipationStats, DepartmentParticipation
    from src.prisma.client import db

    now          = datetime.now(timezone.utc)
    month_start  = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)

    active_employees, reviews_this_month, reviews_last_month, all_departments = await asyncio.gather(
        db.employees.find_many(
            where={"status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}}
        ),
        db.reviews.find_many(where={"review_at": {"gte": month_start}}),
        db.reviews.find_many(where={"review_at": {"gte": last_month_start, "lt": month_start}}),
        db.departments.find_many(),
    )

    total_employees = len(active_employees)
    active_ids      = {e.employee_id for e in active_employees}

    reviewers  = {r.reviewer_id for r in reviews_this_month} & active_ids
    receivers  = {r.receiver_id for r in reviews_this_month} & active_ids
    both       = reviewers & receivers
    neither    = active_ids - reviewers - receivers

    givers_only    = reviewers - both
    receivers_only = receivers - both

    def pct(n: int) -> float:
        return round(n / total_employees * 100, 1) if total_employees > 0 else 0.0

    pie = [
        ParticipationSlice(name="Both",           value=pct(len(both))),
        ParticipationSlice(name="Givers only",    value=pct(len(givers_only))),
        ParticipationSlice(name="Receivers only", value=pct(len(receivers_only))),
        ParticipationSlice(name="Inactive",       value=pct(len(neither))),
    ]

    active_count = len(reviewers | receivers)
    avg_this     = round(len(reviews_this_month) / total_employees, 2) if total_employees > 0 else 0.0
    avg_last     = round(len(reviews_last_month) / total_employees, 2) if total_employees > 0 else 0.0

    stats = ParticipationStats(
        total_employees          =total_employees,
        active_participants      =active_count,
        non_participants         =len(neither),
        participation_rate       =pct(active_count),
        avg_reviews_per_employee =avg_this,
        avg_reviews_last_month   =avg_last,
    )

    dept_map = {d.department_id: d.department_name for d in all_departments}
    emp_dept = {e.employee_id: e.department_id for e in active_employees}
    dept_active_counts: dict = {}
    dept_total_counts:  dict = {}

    for emp_id in active_ids:
        dept_id = emp_dept.get(emp_id)
        if not dept_id:
            continue
        dept_total_counts[dept_id] = dept_total_counts.get(dept_id, 0) + 1
        if emp_id in (reviewers | receivers):
            dept_active_counts[dept_id] = dept_active_counts.get(dept_id, 0) + 1

    by_department = [
        DepartmentParticipation(
            department_id=str(dept_id),
            name=dept_map.get(dept_id, "Unknown"),
            rate=round(dept_active_counts.get(dept_id, 0) / total * 100, 1) if total > 0 else 0.0,
            active=dept_active_counts.get(dept_id, 0),
            total=total,
        )
        for dept_id, total in dept_total_counts.items()
    ]

    result = ParticipationOverview(
        pie=pie,
        stats=stats,
        by_department=by_department,
    )

    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition Trend  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_trend(range_: str):
    """Time-series review activity. range: 3m → weekly buckets, 6m/1y → monthly."""
    from src.analytics.schemas import RecognitionTrend
    from dateutil.relativedelta import relativedelta

    key    = f"dashboard:recognition_trend:{range_}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    logger.debug("cache trend key=%s %s", key, "HIT" if cached is not None else "MISS")
    if cached is not None:
        return RecognitionTrend(**cached)

    from src.prisma.client import db
    now = datetime.now(timezone.utc)

    from src.analytics.schemas import TrendPoint

    if range_ == "3m":
        n_buckets = 12
        # Anchor to exactly 12 weeks back so no gap between last bucket and now
        start = now - relativedelta(weeks=n_buckets)

        reviews = await db.reviews.find_many(
            where={"review_at": {"gte": start}},
            order={"review_at": "asc"},
        )

        points: list[TrendPoint] = []
        for i in builtins_range(n_buckets):
            b_start = start + relativedelta(weeks=i)
            b_end   = b_start + relativedelta(weeks=1)
            label   = b_start.strftime("%b %d")
            in_bucket = [r for r in reviews if b_start <= r.review_at.replace(tzinfo=timezone.utc) < b_end]
            points.append(TrendPoint(
                label=label,
                given=len({r.reviewer_id for r in in_bucket}),
                received=len(in_bucket),
            ))
    else:
        # Monthly buckets — compute backwards from now so current month is always included
        n_buckets = 6 if range_ == "6m" else 12
        # Build bucket boundaries from oldest → newest
        bucket_starts = [
            (now - relativedelta(months=i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            for i in builtins_range(n_buckets - 1, -1, -1)  # n-1 months ago → 0 (current month)
        ]
        start = bucket_starts[0]

        reviews = await db.reviews.find_many(
            where={"review_at": {"gte": start}},
            order={"review_at": "asc"},
        )

        points: list[TrendPoint] = []
        for b_start in bucket_starts:
            b_end = b_start + relativedelta(months=1)
            label = b_start.strftime("%b %Y")
            in_bucket = [r for r in reviews if b_start <= r.review_at.replace(tzinfo=timezone.utc) < b_end]
            points.append(TrendPoint(
                label=label,
                given=len({r.reviewer_id for r in in_bucket}),
                received=len(in_bucket),
            ))

    result = RecognitionTrend(data=points)
    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition per User  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_users(range_: str, page: int, limit: int):
    """Paginated employees with given/received review counts for the period."""
    from src.analytics.schemas import PaginatedUserRecognition
    import asyncio, math

    key    = f"dashboard:recognition_users:{range_}:{page}:{limit}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return PaginatedUserRecognition(**cached)

    from src.prisma.client import db
    now   = datetime.now(timezone.utc)
    start = _range_start(now, range_)

    employees, reviews, departments = await asyncio.gather(
        db.employees.find_many(
            where={"status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}}
        ),
        db.reviews.find_many(where={"review_at": {"gte": start}}),
        db.departments.find_many(),
    )

    dept_name = {d.department_id: d.department_name for d in departments}
    emp_dept  = {e.employee_id: e.department_id for e in employees}

    given_map:    dict = {}
    received_map: dict = {}
    for r in reviews:
        given_map[r.reviewer_id]    = given_map.get(r.reviewer_id, 0) + 1
        received_map[r.receiver_id] = received_map.get(r.receiver_id, 0) + 1

    rows = sorted([
        {
            "employee_id": str(e.employee_id),
            "username":    e.username,
            "department":  dept_name.get(emp_dept.get(e.employee_id), "Unknown"),
            "given":       given_map.get(e.employee_id, 0),
            "received":    received_map.get(e.employee_id, 0),
        }
        for e in employees
    ], key=lambda x: x["given"], reverse=True)

    total = len(rows)
    pages = math.ceil(total / limit) if total else 0
    skip  = (page - 1) * limit
    items = rows[skip: skip + limit]

    result = PaginatedUserRecognition(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Recognition per Team  — SHORT (300s / 60s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_recognition_teams(range_: str, page: int, limit: int):
    """Paginated departments with aggregated given/received review counts."""
    from src.analytics.schemas import PaginatedTeamRecognition
    import asyncio, math

    key    = f"dashboard:recognition_teams:{range_}:{page}:{limit}"
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return PaginatedTeamRecognition(**cached)

    from src.prisma.client import db
    now   = datetime.now(timezone.utc)
    start = _range_start(now, range_)

    departments, employees, reviews = await asyncio.gather(
        db.departments.find_many(),
        db.employees.find_many(
            where={"status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}}
        ),
        db.reviews.find_many(where={"review_at": {"gte": start}}),
    )

    emp_dept = {e.employee_id: e.department_id for e in employees}
    dept_members: dict = {}
    for e in employees:
        if e.department_id:
            dept_members[e.department_id] = dept_members.get(e.department_id, 0) + 1

    dept_given:    dict = {}
    dept_received: dict = {}
    for r in reviews:
        d = emp_dept.get(r.reviewer_id)
        if d:
            dept_given[d] = dept_given.get(d, 0) + 1
        d = emp_dept.get(r.receiver_id)
        if d:
            dept_received[d] = dept_received.get(d, 0) + 1

    dept_map = {d.department_id: d.department_name for d in departments}
    rows = sorted([
        {
            "department_id": str(dept_id),
            "name":          dept_map.get(dept_id, "Unknown"),
            "members":       members,
            "given":         dept_given.get(dept_id, 0),
            "received":      dept_received.get(dept_id, 0),
        }
        for dept_id, members in dept_members.items()
    ], key=lambda x: x["given"], reverse=True)

    total = len(rows)
    pages = math.ceil(total / limit) if total else 0
    skip  = (page - 1) * limit
    items = rows[skip: skip + limit]

    result = PaginatedTeamRecognition(
        items=items,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
    await cache_set(key, result.model_dump(), ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _range_start(now: datetime, range: str) -> datetime:
    from dateutil.relativedelta import relativedelta
    mapping = {"week": relativedelta(weeks=1), "month": relativedelta(months=1),
               "quarter": relativedelta(months=3), "year": relativedelta(years=1)}
    return now - mapping.get(range, relativedelta(months=1))