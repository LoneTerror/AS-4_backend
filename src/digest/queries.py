"""
digest/queries.py
─────────────────
All DB reads for the weekly digest are isolated here.
Queries use the `reviews` table (reviewer_id, receiver_id, raw_points, review_at)
which is the source of truth for recognitions.

manager_id filter:
  When provided, only reviews where EITHER the reviewer OR the receiver is a
  direct report of that manager are included. This gives the manager a full
  picture of their team's engagement — recognitions given by team members AND
  recognitions received by team members — not just inbound recognitions.

  top_giver and top_receiver are additionally filtered to only team members,
  so the "top" slots always reflect someone on the manager's actual team.

BUG FIX (previous):
  TopPerformer.employee_id is declared as UUID4 in schemas.py but was being
  assigned a plain str. Now explicitly cast via UUID().

BUG FIX (this revision):
  The original filter used receiver_id IN team_ids only. This meant:
    - Recognitions given BY team members to outsiders were invisible.
    - Top giver could be an employee from a completely different team.
  Fixed by using OR: reviewer_id IN team_ids OR receiver_id IN team_ids.
  Top performer counts are then restricted to team members only.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from prisma import Prisma

from .schemas import TopPerformer, WeeklyDigestData


def get_week_boundaries(week_start: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Return Monday 00:00 UTC → Sunday 23:59:59 UTC.
    Defaults to the most recently completed week if week_start is None.
    """
    if week_start is None:
        today = datetime.now(tz=timezone.utc).date()
        days_since_monday = today.weekday()
        last_monday = today - timedelta(days=days_since_monday + 7)
        start = datetime(last_monday.year, last_monday.month, last_monday.day,
                         tzinfo=timezone.utc)
    else:
        start = week_start.replace(hour=0, minute=0, second=0, microsecond=0,
                                   tzinfo=timezone.utc)

    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start, end


async def _get_direct_report_ids(db: Prisma, manager_id: str) -> list[str]:
    """
    Return the employee_ids of all direct reports of the given manager.
    Uses employees.manager_id FK (one level deep — not recursive).
    """
    reports = await db.employees.find_many(
        where={"manager_id": manager_id}
    )
    return [str(e.employee_id) for e in reports]


async def fetch_weekly_digest_data(
    db: Prisma,
    week_start: Optional[datetime] = None,
    manager_id: Optional[str] = None,
) -> WeeklyDigestData:
    """
    Build WeeklyDigestData from the reviews table.
    Only REVIEW_ACTIVE reviews are counted.

    If manager_id is provided, only reviews where the receiver is a direct
    report of that manager are included — scoping the digest to that team.
    If manager_id is None, all platform reviews are included.
    """
    start, end = get_week_boundaries(week_start)

    empty = WeeklyDigestData(
        week_start=start,
        week_end=end,
        total_recognitions=0,
        total_points_awarded=0.0,
        unique_givers=0,
        unique_receivers=0,
    )

    # ── 1. Resolve approved status IDs ───────────────────────────────────────
    approved_statuses = await db.status_master.find_many(
        where={"status_code": "REVIEW_ACTIVE", "entity_type": "REVIEW"}
    )
    if not approved_statuses:
        return empty

    approved_status_ids = [s.status_id for s in approved_statuses]

    # ── 2. Build where clause ─────────────────────────────────────────────────
    where: dict = {
        "review_at": {"gte": start, "lte": end},
        "status_id": {"in": approved_status_ids},
    }

    # Scope to team if manager_id provided
    team_ids: set[str] = set()
    if manager_id:
        raw_ids = await _get_direct_report_ids(db, manager_id)
        if not raw_ids:
            # Manager has no direct reports — return empty digest
            return empty
        team_ids = set(raw_ids)
        # FIX: use OR so we capture recognitions given BY team members
        # (reviewer in team) AND recognitions received BY team members
        # (receiver in team).  The old receiver-only filter hid half of
        # the team's activity and allowed outsiders to appear as top givers.
        where["OR"] = [
            {"reviewer_id": {"in": list(team_ids)}},
            {"receiver_id": {"in": list(team_ids)}},
        ]

    # ── 3. Fetch reviews ──────────────────────────────────────────────────────
    reviews = await db.reviews.find_many(
        where=where,
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "employees_reviews_receiver_idToemployees": True,
        },
    )

    if not reviews:
        return empty

    # ── 4. Aggregate ──────────────────────────────────────────────────────────
    total_points = sum(r.raw_points or 0.0 for r in reviews)

    giver_counts: dict[str, int] = {}
    giver_names:  dict[str, str] = {}
    for r in reviews:
        rid = str(r.reviewer_id)
        # When scoped to a team, only count a giver if they are a team member.
        # (The OR filter may have pulled in reviews where the reviewer is an
        # outsider who recognised a team member — they should not appear as
        # top giver in this manager's digest.)
        if team_ids and rid not in team_ids:
            continue
        giver_counts[rid] = giver_counts.get(rid, 0) + 1
        emp = r.employees_reviews_reviewer_idToemployees
        if emp:
            giver_names[rid] = emp.username

    receiver_counts: dict[str, int] = {}
    receiver_names:  dict[str, str] = {}
    for r in reviews:
        rid = str(r.receiver_id)
        # Symmetrically, only count a receiver if they are a team member.
        if team_ids and rid not in team_ids:
            continue
        receiver_counts[rid] = receiver_counts.get(rid, 0) + 1
        emp = r.employees_reviews_receiver_idToemployees
        if emp:
            receiver_names[rid] = emp.username

    # ── 5. Top performers ─────────────────────────────────────────────────────
    # Cast str → UUID to satisfy TopPerformer.employee_id (UUID4) type.
    top_giver: Optional[TopPerformer] = None
    if giver_counts:
        top_id = max(giver_counts, key=lambda k: giver_counts[k])
        top_giver = TopPerformer(
            employee_id=UUID(top_id),
            username=giver_names.get(top_id, "Unknown"),
            count=giver_counts[top_id],
        )

    top_receiver: Optional[TopPerformer] = None
    if receiver_counts:
        top_id = max(receiver_counts, key=lambda k: receiver_counts[k])
        top_receiver = TopPerformer(
            employee_id=UUID(top_id),
            username=receiver_names.get(top_id, "Unknown"),
            count=receiver_counts[top_id],
        )

    return WeeklyDigestData(
        week_start=start,
        week_end=end,
        total_recognitions=len(reviews),
        total_points_awarded=round(total_points, 2),
        unique_givers=len(giver_counts),
        unique_receivers=len(receiver_counts),
        top_giver=top_giver,
        top_receiver=top_receiver,
    )