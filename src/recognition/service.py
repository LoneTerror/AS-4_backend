"""
src/recognition/service.py
───────────────────────────
Recognition service — owns: reviews, review_categories, review_category_tags.

DECOUPLING CHANGE
──────────────────
Previously create_review() called POST /aabhar/v1/wallets/credit-from-review
synchronously.  Replaced with a fire-and-forget publish() to the
'events:review.created' Redis Stream.  The Wallet service's
review_created_consumer_loop credits points asynchronously.

Result: review creation never fails because the Wallet service is slow
or temporarily unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import Optional

from fastapi import HTTPException

from src.common.event_publisher import publish
from src.prisma.client import db
from src.recognition.points_engine import calculate_points
from src.recognition.schemas import (
    ReviewCategoryCreateRequest,
    ReviewCategoryUpdateRequest,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Review Categories
# ─────────────────────────────────────────────────────────────────────────────

async def list_review_categories(page: int = 1, limit: int = 20, active_only: bool = False):
    where = {"is_active": True} if active_only else {}

    if where:
        total = await db.review_categories.count(where=where)
        rows = await db.review_categories.find_many(
            where=where,
            order={"category_name": "asc"},
            skip=(page - 1) * limit,
            take=limit,
        )
    else:
        total = await db.review_categories.count()
        rows = await db.review_categories.find_many(
            order={"category_name": "asc"},
            skip=(page - 1) * limit,
            take=limit,
        )
    return {
        "data": rows,
        "pagination": {
            "current_page": page, "per_page": limit, "total": total,
            "total_pages":  math.ceil(total / limit) if total else 0,
            "has_next":     (page * limit) < total,
            "has_previous": page > 1,
        },
    }


async def create_review_category(body: ReviewCategoryCreateRequest, current_user_id: str):
    existing = await db.review_categories.find_first(where={
        "OR": [{"category_code": body.category_code}, {"category_name": body.category_name}]
    })
    if existing:
        raise HTTPException(status_code=409, detail="Category code or name already exists")
    return await db.review_categories.create(data={
        "category_code": body.category_code,
        "category_name": body.category_name,
        "multiplier":    body.multiplier,
        "description":   body.description,
        "is_active":     True,
        "created_by":    current_user_id,
        "updated_by":    current_user_id,
        "updated_at":    _now(),
    })


async def update_review_category(
    category_id: str, body: ReviewCategoryUpdateRequest, current_user_id: str
):
    existing = await db.review_categories.find_unique(where={"category_id": category_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")
    data: dict = {"updated_by": current_user_id, "updated_at": _now()}
    for field in ("category_code", "category_name", "multiplier", "description", "is_active"):
        val = getattr(body, field, None)
        if val is not None:
            data[field] = val
    return await db.review_categories.update(where={"category_id": category_id}, data=data)


# ─────────────────────────────────────────────────────────────────────────────
# Reviews
# ─────────────────────────────────────────────────────────────────────────────

async def list_reviews(
    page: int = 1,
    limit: int = 20,
    reviewer_id: Optional[str] = None,
    receiver_id: Optional[str] = None,
):
    where: dict = {}
    if reviewer_id:
        where["reviewer_id"] = reviewer_id
    if receiver_id:
        where["receiver_id"] = receiver_id

    # Prisma 0.15.0 bug: passing where={} leaks enclosing scope into query builder.
    # Fix: only pass where= when it has actual filters.
    if where:
        total = await db.reviews.count(where=where)
        rows = await db.reviews.find_many(
            where=where,
            include={
                "employees_reviews_reviewer_idToemployees": True,
                "review_category_tags": True,
            },
            order={"review_at": "desc"},
            skip=(page - 1) * limit,
            take=limit,
        )
    else:
        total = await db.reviews.count()
        rows = await db.reviews.find_many(
            include={
                "employees_reviews_reviewer_idToemployees": True,
                "review_category_tags": True,
            },
            order={"review_at": "desc"},
            skip=(page - 1) * limit,
            take=limit,
        )

    return {
        "data": [_serialize_review(r) for r in rows],
        "pagination": {
            "current_page": page, "per_page": limit, "total": total,
            "total_pages":  math.ceil(total / limit) if total else 0,
            "has_next":     (page * limit) < total,
            "has_previous": page > 1,
        },
    }
async def get_review(review_id: str):
    row = await db.reviews.find_unique(
        where={"review_id": review_id},
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "review_category_tags": True,
        },
    )
    if not row:
        raise HTTPException(status_code=404, detail="Review not found")
    return _serialize_review(row)


async def create_review(body: ReviewCreateRequest, reviewer_id: str):
    # ── Validate categories ───────────────────────────────────────────────────
    cat_ids = [str(cid) for cid in body.category_ids]
    categories = await db.review_categories.find_many(
        where={"category_id": {"in": cat_ids}, "is_active": True}
    )
    if len(categories) != len(cat_ids):
        raise HTTPException(status_code=400, detail="One or more category IDs are invalid or inactive")

    # ── Calculate points ──────────────────────────────────────────────────────
    reviewer_weight  = await _get_reviewer_weight(reviewer_id)
    total_multiplier = sum(float(c.multiplier) for c in categories)
    pts_result       = calculate_points(
        total_category_multiplier=total_multiplier,
        reviewer_weight=reviewer_weight,
        category_code=",".join(c.category_code for c in categories),
    )
    raw_points = round(pts_result.raw_points)

    # ── Resolve status ────────────────────────────────────────────────────────
    status = await db.status_master.find_first(
        where={"status_code": "ACTIVE", "entity_type": "REVIEW"}
    ) or await db.status_master.find_first(where={"status_code": "ACTIVE"})
    if not status:
        raise HTTPException(status_code=500, detail="No ACTIVE status found in status_master")

    # ── Persist review ────────────────────────────────────────────────────────
    review = await db.reviews.create(data={
        "reviewer_id": reviewer_id,
        "receiver_id": str(body.receiver_id),
        "comment":     body.comment,
        "image_url":   str(body.image_url) if body.image_url else None,
        "video_url":   str(body.video_url) if body.video_url else None,
        "status_id":   status.status_id,
        "raw_points":  raw_points,
        "review_at":   _now(),
        "created_by":  reviewer_id,
        "updated_by":  reviewer_id,
        "updated_at":  _now(),
    })

    # ── Persist category tag snapshots ────────────────────────────────────────
    for cat in categories:
        await db.review_category_tags.create(data={
            "review_id":              review.review_id,
            "category_id":            cat.category_id,
            "category_code_snapshot": cat.category_code,
            "multiplier_snapshot":    float(cat.multiplier),
        })

    # ── Publish event — replaces synchronous HTTP call to Wallet ─────────────
    # Previously: httpx.post("/aabhar/v1/wallets/credit-from-review")
    # Now: fire-and-forget; Wallet's review_created_consumer credits asynchronously.
    await publish("events:review.created", {
        "review_id":   str(review.review_id),
        "reviewer_id": reviewer_id,
        "receiver_id": str(body.receiver_id),
        "raw_points":  str(raw_points),
    })

    logger.info(
        "Review %s created — published review.created (receiver=%s, points=%d)",
        review.review_id, body.receiver_id, raw_points,
    )

    return _serialize_review(await db.reviews.find_unique(
        where={"review_id": review.review_id},
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "review_category_tags": True,
        },
    ))


async def update_review(review_id: str, body: ReviewUpdateRequest, current_user_id: str):
    existing = await db.reviews.find_unique(where={"review_id": review_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Review not found")
    if str(existing.reviewer_id) != current_user_id:
        raise HTTPException(status_code=403, detail="Not authorised to edit this review")

    data: dict = {"updated_by": current_user_id, "updated_at": _now()}
    if body.comment is not None:
        data["comment"] = body.comment
    if body.image_url is not None:
        data["image_url"] = str(body.image_url)
    if body.video_url is not None:
        data["video_url"] = str(body.video_url)

    if body.category_ids is not None:
        cat_ids    = [str(cid) for cid in body.category_ids]
        categories = await db.review_categories.find_many(
            where={"category_id": {"in": cat_ids}, "is_active": True}
        )
        if len(categories) != len(cat_ids):
            raise HTTPException(status_code=400, detail="One or more category IDs invalid or inactive")
        reviewer_weight  = await _get_reviewer_weight(current_user_id)
        total_multiplier = sum(float(c.multiplier) for c in categories)
        pts_result       = calculate_points(
            total_category_multiplier=total_multiplier,
            reviewer_weight=reviewer_weight,
        )
        data["raw_points"] = round(pts_result.raw_points)
        await db.review_category_tags.delete_many(where={"review_id": review_id})
        for cat in categories:
            await db.review_category_tags.create(data={
                "review_id":              review_id,
                "category_id":            cat.category_id,
                "category_code_snapshot": cat.category_code,
                "multiplier_snapshot":    float(cat.multiplier),
            })

    await db.reviews.update(where={"review_id": review_id}, data=data)
    return _serialize_review(await db.reviews.find_unique(
        where={"review_id": review_id},
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "review_category_tags": True,
        },
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Internal endpoints (served by recognition/internal_router.py)
# ─────────────────────────────────────────────────────────────────────────────

async def get_review_stats_internal(employee_id: str) -> dict:
    from dateutil.relativedelta import relativedelta
    now        = _now()
    start_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_last = (start_this - relativedelta(months=1))

    total, this_month, last_month = await asyncio.gather(
        db.reviews.count(where={"receiver_id": employee_id}),
        db.reviews.count(where={"receiver_id": employee_id,
                                 "review_at": {"gte": start_this, "lt": now}}),
        db.reviews.count(where={"receiver_id": employee_id,
                                 "review_at": {"gte": start_last, "lt": start_this}}),
    )
    return {"reviews_total": total, "reviews_this_month": this_month, "reviews_last_month": last_month}


async def get_recent_reviews_internal(employee_id: str, limit: int = 5) -> list:
    rows = await db.reviews.find_many(
        where={"receiver_id": employee_id},
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "review_category_tags": True,
        },
        order={"review_at": "desc"},
        take=limit,
    )
    return [_serialize_review(r) for r in rows]


async def get_recognition_trend_internal(range_: str) -> dict:
    """Time-series review activity — used by Analytics."""
    from dateutil.relativedelta import relativedelta

    now = _now()
    builtins_range = range

    if range_ == "3m":
        n_buckets = 12
        start     = now - relativedelta(weeks=n_buckets)
        reviews   = await db.reviews.find_many(where={"review_at": {"gte": start}}, order={"review_at": "asc"})
        points    = []
        for i in builtins_range(n_buckets):
            b_start = start + relativedelta(weeks=i)
            b_end   = b_start + relativedelta(weeks=1)
            bucket  = [r for r in reviews if b_start <= r.review_at.replace(tzinfo=timezone.utc) < b_end]
            points.append({"label": b_start.strftime("%b %d"), "given": len({r.reviewer_id for r in bucket}), "received": len(bucket)})
    else:
        n_buckets     = 6 if range_ == "6m" else 12
        bucket_starts = [
            (now - relativedelta(months=i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            for i in builtins_range(n_buckets - 1, -1, -1)
        ]
        start   = bucket_starts[0]
        reviews = await db.reviews.find_many(where={"review_at": {"gte": start}}, order={"review_at": "asc"})
        points  = []
        for b_start in bucket_starts:
            b_end  = b_start + relativedelta(months=1)
            bucket = [r for r in reviews if b_start <= r.review_at.replace(tzinfo=timezone.utc) < b_end]
            points.append({"label": b_start.strftime("%b %Y"), "given": len({r.reviewer_id for r in bucket}), "received": len(bucket)})

    return {"data": points}


async def get_recognition_by_user_internal(range_: str, page: int, limit: int) -> dict:
    from dateutil.relativedelta import relativedelta
    mapping = {"week": relativedelta(weeks=1), "month": relativedelta(months=1),
               "quarter": relativedelta(months=3), "year": relativedelta(years=1)}
    start = _now() - mapping.get(range_, relativedelta(months=1))

    employees, reviews, departments = await asyncio.gather(
        db.employees.find_many(),
        db.reviews.find_many(where={"review_at": {"gte": start}}),
        db.departments.find_many(),
    )
    dept_name = {str(d.department_id): d.department_name for d in departments}
    emp_dept  = {str(e.employee_id): str(e.department_id) for e in employees}
    given_map: dict = {}
    recv_map:  dict = {}
    for r in reviews:
        given_map[str(r.reviewer_id)] = given_map.get(str(r.reviewer_id), 0) + 1
        recv_map[str(r.receiver_id)]  = recv_map.get(str(r.receiver_id), 0) + 1

    rows = sorted([
        {"employee_id": str(e.employee_id), "username": e.username,
         "department": dept_name.get(emp_dept.get(str(e.employee_id), ""), "Unknown"),
         "given": given_map.get(str(e.employee_id), 0),
         "received": recv_map.get(str(e.employee_id), 0)}
        for e in employees
    ], key=lambda x: x["given"], reverse=True)

    total = len(rows)
    skip  = (page - 1) * limit
    return {"items": rows[skip:skip + limit], "total": total,
            "page": page, "limit": limit, "pages": math.ceil(total / limit) if total else 0}


async def get_recognition_by_team_internal(range_: str, page: int, limit: int) -> dict:
    from dateutil.relativedelta import relativedelta
    mapping = {"week": relativedelta(weeks=1), "month": relativedelta(months=1),
               "quarter": relativedelta(months=3), "year": relativedelta(years=1)}
    start = _now() - mapping.get(range_, relativedelta(months=1))

    departments, employees, reviews = await asyncio.gather(
        db.departments.find_many(),
        db.employees.find_many(),
        db.reviews.find_many(where={"review_at": {"gte": start}}),
    )
    emp_dept      = {str(e.employee_id): str(e.department_id) for e in employees}
    dept_members: dict = {}
    for e in employees:
        if e.department_id:
            k = str(e.department_id)
            dept_members[k] = dept_members.get(k, 0) + 1

    dept_given:    dict = {}
    dept_received: dict = {}
    for r in reviews:
        if d := emp_dept.get(str(r.reviewer_id)):
            dept_given[d]    = dept_given.get(d, 0) + 1
        if d := emp_dept.get(str(r.receiver_id)):
            dept_received[d] = dept_received.get(d, 0) + 1

    dept_name_map = {str(d.department_id): d.department_name for d in departments}
    rows = sorted([
        {"department_id": did, "name": dept_name_map.get(did, "Unknown"), "members": members,
         "given": dept_given.get(did, 0), "received": dept_received.get(did, 0)}
        for did, members in dept_members.items()
    ], key=lambda x: x["given"], reverse=True)

    total = len(rows)
    skip  = (page - 1) * limit
    return {"items": rows[skip:skip + limit], "total": total,
            "page": page, "limit": limit, "pages": math.ceil(total / limit) if total else 0}


async def get_participation_internal() -> dict:
    from dateutil.relativedelta import relativedelta
    now       = _now()
    month_ago = now - relativedelta(months=1)

    all_reviews, recent_reviews, departments, employees = await asyncio.gather(
        db.reviews.find_many(),
        db.reviews.find_many(where={"review_at": {"gte": month_ago}}),
        db.departments.find_many(),
        db.employees.find_many(
            include={"status_master_employees_status_idTostatus_master": True}
        ),
    )
    active_emps = [
        e for e in employees
        if e.status_master_employees_status_idTostatus_master
        and e.status_master_employees_status_idTostatus_master.status_code == "ACTIVE"
    ]
    total_active = len(active_emps)
    active_ids   = {str(e.employee_id) for e in active_emps}
    participants = ({str(r.reviewer_id) for r in all_reviews} | {str(r.receiver_id) for r in all_reviews}) & active_ids
    active_p     = len(participants)
    rate         = round(active_p / total_active * 100, 1) if total_active else 0.0

    emp_dept     = {str(e.employee_id): str(e.department_id) for e in active_emps if e.department_id}
    dept_members: dict = {}
    for e in active_emps:
        if e.department_id:
            k = str(e.department_id)
            dept_members[k] = dept_members.get(k, 0) + 1

    dept_p: dict[str, set] = {}
    for r in all_reviews:
        for eid in (str(r.reviewer_id), str(r.receiver_id)):
            if d := emp_dept.get(eid):
                dept_p.setdefault(d, set()).add(eid)

    dept_name = {str(d.department_id): d.department_name for d in departments}
    return {
        "pie": [{"name": "Active participants", "value": rate},
                {"name": "Non-participants",    "value": round(100 - rate, 1)}],
        "stats": {
            "total_employees": total_active, "active_participants": active_p,
            "non_participants": total_active - active_p, "participation_rate": rate,
            "avg_reviews_per_employee": round(len(all_reviews) / total_active, 2) if total_active else 0.0,
            "avg_reviews_last_month":  round(len(recent_reviews) / total_active, 2) if total_active else 0.0,
        },
        "by_department": [
            {"department_id": did, "name": dept_name.get(did, "Unknown"),
             "active": len(dept_p.get(did, set())), "total": members,
             "rate": round(len(dept_p.get(did, set())) / members * 100, 1) if members else 0.0}
            for did, members in dept_members.items()
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_reviewer_weight(reviewer_id: str) -> float:
    try:
        roles = await db.employee_roles.find_many(
            where={"employee_id": reviewer_id, "is_active": True},
            include={"roles": True},
        )
        for ra in roles:
            if ra.roles and hasattr(ra.roles, "reviewer_weight") and ra.roles.reviewer_weight:
                return float(ra.roles.reviewer_weight)
    except Exception as exc:
        logger.warning("Could not resolve reviewer_weight for %s: %s", reviewer_id, exc)
    return 1.0


def _serialize_review(row) -> dict:
    if row is None:
        return {}
    tags = row.review_category_tags or []
    reviewer = row.employees_reviews_reviewer_idToemployees  # already included
    return {
        "review_id":      row.review_id,
        "reviewer_id":    row.reviewer_id,
        "reviewer_name":  reviewer.username if reviewer else "Someone", 
        "receiver_id":    row.receiver_id,
        "comment":        row.comment,
        "image_url":      row.image_url,
        "video_url":      row.video_url,
        "status_id":      row.status_id,
        "review_at":      row.review_at,
        "created_at":     row.created_at,
        "created_by":     row.created_by,
        "updated_at":     row.updated_at,
        "updated_by":     row.updated_by,
        "raw_points":     row.raw_points,
        "category_tags":  [{"category_id": t.category_id, "category_code": t.category_code_snapshot,
                             "multiplier_snapshot": t.multiplier_snapshot} for t in tags],
        "category_ids":   [t.category_id for t in tags],
        "category_codes": [t.category_code_snapshot for t in tags],
    }
async def get_review_stats_batch_internal(employee_ids: list[str]) -> dict:
    """
    Bulk review stats for a list of employee_ids.
    Returns a dict keyed by employee_id with shape:
        {reviews_total, reviews_this_month, reviews_last_month}
 
    Replaces N calls to get_review_stats_internal() with 3 DB queries total,
    regardless of how many employees are requested.
 
    Called by recognition/internal_router.py → GET /internal/reviews/stats/batch
    """
    from src.prisma.client import db
 
    if not employee_ids:
        return {}
 
    now   = datetime.now(timezone.utc)
    start_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_last = start_this - relativedelta(months=1)
    end_last   = start_this  # last month ends where this month begins
 
    zero = {"reviews_total": 0, "reviews_this_month": 0, "reviews_last_month": 0}
 
    # Three bulk queries — one per time bucket
    all_reviews, reviews_this, reviews_last = await asyncio.gather(
        db.reviews.find_many(
            where={"receiver_id": {"in": employee_ids}},
            # only select receiver_id to keep payload minimal
        ),
        db.reviews.find_many(
            where={
                "receiver_id": {"in": employee_ids},
                "review_at":   {"gte": start_this},
            },
        ),
        db.reviews.find_many(
            where={
                "receiver_id": {"in": employee_ids},
                "review_at":   {"gte": start_last, "lt": end_last},
            },
        ),
    )
 
    # Aggregate counts per employee
    totals:     dict[str, int] = {eid: 0 for eid in employee_ids}
    this_month: dict[str, int] = {eid: 0 for eid in employee_ids}
    last_month: dict[str, int] = {eid: 0 for eid in employee_ids}
 
    for r in all_reviews:
        rid = str(r.receiver_id)
        if rid in totals:
            totals[rid] += 1
    for r in reviews_this:
        rid = str(r.receiver_id)
        if rid in this_month:
            this_month[rid] += 1
    for r in reviews_last:
        rid = str(r.receiver_id)
        if rid in last_month:
            last_month[rid] += 1
 
    return {
        eid: {
            "reviews_total":      totals.get(eid, 0),
            "reviews_this_month": this_month.get(eid, 0),
            "reviews_last_month": last_month.get(eid, 0),
        }
        for eid in employee_ids
    }