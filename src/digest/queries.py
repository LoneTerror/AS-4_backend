"""
digest/queries.py
─────────────────
All DB reads for the weekly digest are isolated here.
Queries use the `reviews` table (reviewer_id, receiver_id, raw_points, review_at)
which is the source of truth for recognitions.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from prisma import Prisma

from .schemas import TopPerformer, WeeklyDigestData


def get_week_boundaries(week_start: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    Return Monday 00:00 UTC → Sunday 23:59:59 UTC.
    Defaults to the most recently completed week if week_start is None.
    """
    if week_start is None:
        today = datetime.now(tz=timezone.utc).date()
        # days_since_monday: 0=Mon … 6=Sun
        days_since_monday = today.weekday()
        last_monday = today - timedelta(days=days_since_monday + 7)
        start = datetime(last_monday.year, last_monday.month, last_monday.day,
                         tzinfo=timezone.utc)
    else:
        # Normalise to midnight UTC of the supplied date
        start = week_start.replace(hour=0, minute=0, second=0, microsecond=0,
                                   tzinfo=timezone.utc)

    end = start + timedelta(days=7) - timedelta(seconds=1)
    return start, end


async def fetch_weekly_digest_data(
    db: Prisma,
    week_start: Optional[datetime] = None,
) -> WeeklyDigestData:
    """
    Build the full WeeklyDigestData from the `reviews` table.
    Only APPROVED reviews are counted (status_code == 'APPROVED').
    """
    start, end = get_week_boundaries(week_start)

    # ── 1. Fetch all approved reviews in the window ──────────────────────────
    approved_statuses = await db.status_master.find_many(
        where={"status_code": "REVIEW_ACTIVE", "entity_type": "REVIEW"}
    )
    if not approved_statuses:
        return WeeklyDigestData(
            week_start=start,
            week_end=end,
            total_recognitions=0,
            total_points_awarded=0.0,
            unique_givers=0,
            unique_receivers=0,
        )

    approved_status_ids = [s.status_id for s in approved_statuses]

    reviews = await db.reviews.find_many(
        where={
            "review_at": {"gte": start, "lte": end},
            "status_id": {"in": approved_status_ids},
        },
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "employees_reviews_receiver_idToemployees": True,
        },
    )

    if not reviews:
        return WeeklyDigestData(
            week_start=start,
            week_end=end,
            total_recognitions=0,
            total_points_awarded=0.0,
            unique_givers=0,
            unique_receivers=0,
        )

    # ── 2. Aggregate ─────────────────────────────────────────────────────────
    total_points = sum(r.raw_points or 0.0 for r in reviews)

    # Giver counts  (reviewer_id → count)
    giver_counts: dict[str, int] = {}
    giver_names: dict[str, str] = {}
    for r in reviews:
        rid = str(r.reviewer_id)
        giver_counts[rid] = giver_counts.get(rid, 0) + 1
        emp = r.employees_reviews_reviewer_idToemployees
        if emp:
            giver_names[rid] = emp.username

    # Receiver counts  (receiver_id → count)
    receiver_counts: dict[str, int] = {}
    receiver_names: dict[str, str] = {}
    for r in reviews:
        rid = str(r.receiver_id)
        receiver_counts[rid] = receiver_counts.get(rid, 0) + 1
        emp = r.employees_reviews_receiver_idToemployees
        if emp:
            receiver_names[rid] = emp.username

    # ── 3. Top giver / receiver ───────────────────────────────────────────────
    top_giver: Optional[TopPerformer] = None
    if giver_counts:
        top_giver_id = max(giver_counts, key=lambda k: giver_counts[k])
        top_giver = TopPerformer(
            employee_id=top_giver_id,
            username=giver_names.get(top_giver_id, "Unknown"),
            count=giver_counts[top_giver_id],
        )

    top_receiver: Optional[TopPerformer] = None
    if receiver_counts:
        top_receiver_id = max(receiver_counts, key=lambda k: receiver_counts[k])
        top_receiver = TopPerformer(
            employee_id=top_receiver_id,
            username=receiver_names.get(top_receiver_id, "Unknown"),
            count=receiver_counts[top_receiver_id],
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