import asyncio
import logging
import math
from datetime import datetime, timezone
from fastapi import HTTPException, status

from src.prisma.client import db
from src.common.dependencies import CurrentUser
from src.common.cache import (
    cache_get, cache_set, cache_delete, invalidate_pattern,
    TTL_VOLATILE,  L1_VOLATILE,
    TTL_MEDIUM,    L1_MEDIUM,
    TTL_SHORT,     L1_SHORT,
)
from src.recognition.schemas import (
    ReviewCreateRequest,
    ReviewUpdateRequest,
    ReviewCategoryCreateRequest,
    ReviewCategoryUpdateRequest,
)
from src.recognition.points_engine import calculate_points
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType

logger = logging.getLogger(__name__)

def _get_notif() -> NotificationService:
    try:
        from src.notifications.redis_client import get_redis
        r = get_redis()
    except RuntimeError:
        r = None
    return NotificationService(db, redis=r)

_ROLE_PRIORITY = ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"]

# ── Cache keys ────────────────────────────────────────────────────────────────
# Reviews        → VOLATILE  (60s  / 30s)   — change often
# Categories     → MEDIUM    (3600s / 300s)  — HR_ADMIN only writes
# Role weight    → MEDIUM    (3600s / 300s)  — rarely changes
# Seasonal mult  → MEDIUM    (3600s / 300s)  — quarterly, rarely changes
# Team headcount → SHORT     (300s  / 60s)   — employees join/leave occasionally

def _key_reviews(user_id: str, page: int, limit: int) -> str:
    return f"recognition:reviews:{user_id}:{page}:{limit}"

def _key_categories(page: int, limit: int, active_only: bool) -> str:
    return f"recognition:categories:{page}:{limit}:{int(active_only)}"

def _key_category(category_id: str) -> str:
    return f"recognition:category:{category_id}"

def _key_role_weight(role_code: str) -> str:
    return f"recognition:role_weight:{role_code}"

def _key_seasonal(quarter: int) -> str:
    return f"recognition:seasonal:{quarter}"

def _key_team_count(department_id: str | None) -> str:
    return f"recognition:team_count:{department_id or 'all'}"

async def invalidate_reviews(user_id: str):
    await invalidate_pattern(f"recognition:reviews:{user_id}:*")

async def invalidate_categories():
    await invalidate_pattern("recognition:categories:*")
    await invalidate_pattern("recognition:category:*")

# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_review_dict(review, tags: list) -> dict:
    try:
        data = {k: v for k, v in vars(review).items() if not k.startswith("_")}
    except TypeError:
        data = {col: getattr(review, col) for col in review.__fields__}

    tag_list = [
        {
            "category_id":         t.category_id,
            "category_code":       t.category_code_snapshot,
            "multiplier_snapshot": float(t.multiplier_snapshot),
        }
        for t in (tags or [])
    ]
    data["category_tags"]  = tag_list
    data["category_ids"]   = [t["category_id"]   for t in tag_list]
    data["category_codes"] = [t["category_code"] for t in tag_list]
    return data


async def _fetch_review_with_tags(review_id: str):
    review = await db.reviews.find_unique(where={"review_id": review_id})
    if not review:
        return None, []
    tags = await db.review_category_tags.find_many(
        where={"review_id": review_id},
        order={"created_at": "asc"},
    )
    return review, tags


async def _get_cached_category(category_id: str) -> dict | None:
    """
    Fetch a single review category with MEDIUM-tier caching.
    Returns a plain dict with {category_id, category_code, multiplier, is_active}
    or None if not found.
    Invalidated by invalidate_categories() on any category write.
    """
    key    = _key_category(category_id)
    cached = await cache_get(key, l1_ttl=L1_MEDIUM)
    if cached is not None:
        return cached

    row = await db.review_categories.find_unique(where={"category_id": category_id})
    if row is None:
        return None

    value = {
        "category_id":   row.category_id,
        "category_code": row.category_code,
        "multiplier":    float(row.multiplier),
        "is_active":     row.is_active,
    }
    await cache_set(key, value, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
    return value


async def _get_cached_role_weight(role_code: str) -> float:
    """
    Fetch reviewer_weight for a role with MEDIUM-tier caching.
    Falls back to 1.0 if the role is not found.
    """
    key    = _key_role_weight(role_code)
    cached = await cache_get(key, l1_ttl=L1_MEDIUM)
    if cached is not None:
        return float(cached)

    role_row = await db.roles.find_first(where={"role_code": role_code})
    weight   = float(role_row.reviewer_weight) if role_row else 1.0
    await cache_set(key, weight, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
    return weight


async def _get_cached_seasonal_multiplier(quarter: int, review_dt: datetime) -> float:
    """
    Fetch the seasonal multiplier for the given quarter with MEDIUM-tier caching.
    Falls back to 1.0 if no row is configured.
    """
    key    = _key_seasonal(quarter)
    cached = await cache_get(key, l1_ttl=L1_MEDIUM)
    if cached is not None:
        return float(cached)

    seasonal_row = await db.seasonal_multipliers.find_first(
        where={
            "quarter": quarter,
            "OR": [
                {"effective_from": None},
                {"effective_from": {"lte": review_dt}},
            ],
        },
        order={"effective_from": "desc"},
    )
    multiplier = float(seasonal_row.multiplier) if seasonal_row else 1.0
    await cache_set(key, multiplier, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
    return multiplier


async def _resolve_multipliers(
    category_ids: list[str],
    reviewer_roles: list[str],
    review_dt: datetime,
) -> tuple[float, float, float, list[dict]]:
    if not category_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one category must be provided",
        )

    tag_snapshots = []
    multipliers   = []

    for cid in category_ids:
        row = await _get_cached_category(cid)
        if not row:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Review category not found: {cid}",
            )
        if not row["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Review category is not active: {row['category_code']}",
            )
        m = row["multiplier"]
        multipliers.append(m)
        tag_snapshots.append({
            "category_id":            cid,
            "multiplier_snapshot":    m,
            "category_code_snapshot": row["category_code"],
        })

    total_multiplier = sum(multipliers)

    # Role weight — cached per role code
    reviewer_weight = 1.0
    for role_code in _ROLE_PRIORITY:
        if role_code in reviewer_roles:
            reviewer_weight = await _get_cached_role_weight(role_code)
            break

    # Seasonal multiplier — cached per quarter
    if review_dt.tzinfo is None:
        review_dt = review_dt.replace(tzinfo=timezone.utc)
    quarter = (review_dt.month - 1) // 3 + 1
    seasonal_multiplier = await _get_cached_seasonal_multiplier(quarter, review_dt)

    return total_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots


async def _get_team_member_count(department_id: str | None) -> int:
    """
    Count active employees (excluding the current user) with SHORT-tier caching.
    TTL 300s — acceptable staleness for a monthly quota check.
    Invalidated implicitly by TTL; explicit invalidation not needed for quota logic.
    """
    key    = _key_team_count(department_id)
    cached = await cache_get(key, l1_ttl=L1_SHORT)
    if cached is not None:
        return max(0, int(cached) - 1)

    where: dict = {
        "status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}
    }
    if department_id:
        where["department_id"] = department_id

    count = await db.employees.count(where=where)
    await cache_set(key, count, ttl=TTL_SHORT, l1_ttl=L1_SHORT)
    return max(0, count - 1)


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class RecognitionService:

    # =========================================================
    # LIST REVIEWS  — VOLATILE tier (60s / 30s)
    # =========================================================
    @staticmethod
    async def list_reviews(page: int, limit: int, current_user: CurrentUser):
        key    = _key_reviews(current_user.id, page, limit)
        cached = await cache_get(key, l1_ttl=L1_VOLATILE)
        logger.debug("cache reviews key=%s %s", key, "HIT" if cached is not None else "MISS")
        if cached is not None:
            return cached

        skip  = (page - 1) * limit
        where = {}
        if not any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"]):
            where["OR"] = [
                {"reviewer_id": current_user.id},
                {"receiver_id": current_user.id},
            ]

        # Run count + page fetch in parallel — saves one round trip
        total, reviews = await asyncio.gather(
            db.reviews.count(where=where),
            db.reviews.find_many(
                where=where,
                skip=skip,
                take=limit,
                order={"review_at": "desc"},
                # No include — avoids N+1 (one extra query per review).
                # Tags are batch-fetched below in a single query.
            ),
        )
        total_pages = math.ceil(total / limit) if total > 0 else 0

        # Single batch fetch for all tags on this page
        review_ids = [r.review_id for r in reviews]
        all_tags   = await db.review_category_tags.find_many(
            where={"review_id": {"in": review_ids}},
            order={"created_at": "asc"},
        )
        tags_by_review: dict[str, list] = {rid: [] for rid in review_ids}
        for tag in all_tags:
            tags_by_review.setdefault(tag.review_id, []).append(tag)

        result = {
            "data": [
                _build_review_dict(r, tags_by_review.get(r.review_id, []))
                for r in reviews
            ],
            "pagination": {
                "current_page": page,
                "per_page":     limit,
                "total":        total,
                "total_pages":  total_pages,
                "has_next":     page < total_pages,
                "has_previous": page > 1 and total_pages > 0,
            },
        }

        await cache_set(key, result, ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
        return result

    # =========================================================
    # GET REVIEW  (access-control sensitive — not cached)
    # =========================================================
    @staticmethod
    async def get_review(review_id: str, current_user: CurrentUser):
        # 1. Fetch from DB
        review = await db.reviews.find_unique(
            where={"review_id": review_id},
            include={"review_category_tags": True},
        )

        # 2. Priority: If it doesn't exist, it's a 404, not a permission issue
        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

        # 3. Then check permissions
        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = review.reviewer_id == current_user.id or review.receiver_id == current_user.id

        if not is_admin and not is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        return _build_review_dict(review, getattr(review, "review_category_tags", []))

    # =========================================================
    # LIST REVIEW CATEGORIES  — MEDIUM tier (3600s / 300s)
    # =========================================================
    @staticmethod
    async def list_review_categories(page: int, limit: int, active_only: bool = True):
        key    = _key_categories(page, limit, active_only)
        cached = await cache_get(key, l1_ttl=L1_MEDIUM)
        logger.debug("cache categories key=%s %s", key, "HIT" if cached is not None else "MISS")
        if cached is not None:
            return cached

        skip  = (page - 1) * limit
        where = {"is_active": True} if active_only else {}

        total      = await db.review_categories.count(where=where)
        categories = await db.review_categories.find_many(
            where=where, skip=skip, take=limit, order={"category_name": "asc"}
        )
        total_pages = math.ceil(total / limit) if total > 0 else 0

        result = {
            "data": [
                {k: v for k, v in vars(c).items() if not k.startswith("_")}
                for c in categories
            ],
            "pagination": {
                "current_page": page,
                "per_page":     limit,
                "total":        total,
                "total_pages":  total_pages,
                "has_next":     page < total_pages,
                "has_previous": page > 1 and total_pages > 0,
            },
        }

        await cache_set(key, result, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
        return result

    # =========================================================
    # CREATE REVIEW CATEGORY
    # =========================================================
    @staticmethod
    async def create_review_category(
        payload: ReviewCategoryCreateRequest,
        current_user: CurrentUser,
    ):
        existing_code = await db.review_categories.find_unique(
            where={"category_code": payload.category_code}
        )
        if existing_code:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A category with code '{payload.category_code}' already exists",
            )

        existing_name = await db.review_categories.find_unique(
            where={"category_name": payload.category_name}
        )
        if existing_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A category with name '{payload.category_name}' already exists",
            )

        now = datetime.now(timezone.utc)

        category = await db.review_categories.create(
            data={
                "category_code": payload.category_code,
                "category_name": payload.category_name,
                "multiplier":    payload.multiplier,
                "description":   payload.description,
                "is_active":     True,
                "created_at":    now,
                "created_by":    current_user.id,
                "updated_at":    now,
                "updated_by":    current_user.id,
            }
        )

        await invalidate_categories()
        logger.info(
            "Review category created | code=%s multiplier=%.4f by=%s",
            category.category_code, float(category.multiplier), current_user.id,
        )

        return {k: v for k, v in vars(category).items() if not k.startswith("_")}

    # =========================================================
    # UPDATE REVIEW CATEGORY
    # =========================================================
    @staticmethod
    async def update_review_category(
        category_id: str,
        payload: ReviewCategoryUpdateRequest,
        current_user: CurrentUser,
    ):
        category = await db.review_categories.find_unique(
            where={"category_id": category_id}
        )
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review category not found",
            )

        update_data: dict = {}

        if payload.category_code is not None:
            conflict = await db.review_categories.find_first(
                where={"category_code": payload.category_code, "NOT": {"category_id": category_id}}
            )
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A category with code '{payload.category_code}' already exists",
                )
            update_data["category_code"] = payload.category_code

        if payload.category_name is not None:
            conflict = await db.review_categories.find_first(
                where={"category_name": payload.category_name, "NOT": {"category_id": category_id}}
            )
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A category with name '{payload.category_name}' already exists",
                )
            update_data["category_name"] = payload.category_name

        if payload.multiplier  is not None: update_data["multiplier"]  = payload.multiplier
        if payload.description is not None: update_data["description"] = payload.description
        if payload.is_active   is not None: update_data["is_active"]   = payload.is_active

        update_data["updated_at"] = datetime.now(timezone.utc)
        update_data["updated_by"] = current_user.id

        updated = await db.review_categories.update(
            where={"category_id": category_id},
            data=update_data,
        )

        await invalidate_categories()
        logger.info(
            "Review category updated | id=%s fields=%s by=%s",
            category_id, list(update_data.keys()), current_user.id,
        )

        return {k: v for k, v in vars(updated).items() if not k.startswith("_")}

    # =========================================================
    # CREATE REVIEW  — invalidates both parties' caches
    # =========================================================
    @staticmethod
    async def create_review(payload: ReviewCreateRequest, current_user: CurrentUser):

        if str(payload.receiver_id) == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Self review not allowed",
            )

        now         = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        receiver_id = str(payload.receiver_id)

        # Parallelise the four independent pre-flight checks
        status_include = {"status_master_employees_status_idTostatus_master": True}
        reviewer, receiver, already_reviewed, review_status_row = await asyncio.gather(
            db.employees.find_unique(where={"employee_id": current_user.id},        include=status_include),
            db.employees.find_unique(where={"employee_id": receiver_id},             include=status_include),
            db.reviews.find_first(where={
                "reviewer_id": current_user.id,
                "receiver_id": receiver_id,
                "review_at":   {"gte": month_start},
            }),
            db.status_master.find_first(where={"entity_type": "REVIEW", "status_code": "REVIEW_ACTIVE"}),
        )

        if not reviewer or (
            not reviewer.status_master_employees_status_idTostatus_master
            or reviewer.status_master_employees_status_idTostatus_master.status_code != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not active and cannot submit reviews",
            )
        if not receiver:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receiver not found")
        if (
            not receiver.status_master_employees_status_idTostatus_master
            or receiver.status_master_employees_status_idTostatus_master.status_code != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Receiver is not active",
            )
        if already_reviewed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="You have already reviewed this person this month",
            )

        is_privileged = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        if not is_privileged:
            monthly_quota, monthly_given = await asyncio.gather(
                _get_team_member_count(current_user.department_id),
                db.reviews.count(where={"reviewer_id": current_user.id, "review_at": {"gte": month_start}}),
            )
            if monthly_quota == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No active team members found to review",
                )
            if monthly_given >= monthly_quota:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Monthly review limit reached ({monthly_given}/{monthly_quota}). "
                        "Your quota equals the number of active teammates in your department."
                    ),
                )

        review_status = review_status_row
        if not review_status:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Review status configuration missing",
            )

        category_ids_str = [str(cid) for cid in payload.category_ids]

        total_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots = (
            await _resolve_multipliers(
                category_ids   = category_ids_str,
                reviewer_roles = current_user.roles,
                review_dt      = now,
            )
        )

        joined_codes = ",".join(t["category_code_snapshot"] for t in tag_snapshots)
        pts = calculate_points(
            rating                    = payload.rating,
            total_category_multiplier = total_multiplier,
            reviewer_weight           = reviewer_weight,
            seasonal_multiplier       = seasonal_multiplier,
            category_code             = joined_codes,
        )

        logger.info(
            "Points calculated | receiver=%s rating=%s categories=%s "
            "total_mult=%.4f raw=%.4f reviewer_roles=%s",
            payload.receiver_id, payload.rating, joined_codes,
            total_multiplier, pts.raw_points, current_user.roles,
        )

        review = await db.reviews.create(
            data={
                "reviewer_id": current_user.id,
                "receiver_id": str(payload.receiver_id),
                "rating":      payload.rating,
                "comment":     payload.comment,
                "image_url":   str(payload.image_url) if payload.image_url else None,
                "video_url":   str(payload.video_url) if payload.video_url else None,
                "status_id":   review_status.status_id,
                "review_at":   now,
                "created_at":  now,
                "created_by":  current_user.id,
                "updated_at":  now,
                "updated_by":  current_user.id,
                "raw_points":  round(pts.raw_points, 4),
            }
        )

        # Batch-insert all tags in parallel
        await asyncio.gather(*[
            db.review_category_tags.create(
                data={
                    "review_id":              review.review_id,
                    "category_id":            snap["category_id"],
                    "multiplier_snapshot":    snap["multiplier_snapshot"],
                    "category_code_snapshot": snap["category_code_snapshot"],
                }
            )
            for snap in tag_snapshots
        ])

        # Invalidate review list caches for both parties in parallel
        await asyncio.gather(
            invalidate_reviews(current_user.id),
            invalidate_reviews(receiver_id),
        )

        try:
            from src.wallet.service import credit_wallet_from_review
            wallet_result = await credit_wallet_from_review(
                review_id    = review.review_id,
                current_user = current_user,
            )
            logger.info(
                "Wallet credited | review=%s credited=%d new_balance=%d",
                review.review_id,
                wallet_result.get("credited_points", 0),
                wallet_result.get("new_balance", 0),
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info("Wallet already credited for review %s", review.review_id)
            else:
                logger.exception("Wallet credit failed for review %s", review.review_id)
        except Exception:
            logger.exception("Unexpected wallet credit failure for review %s", review.review_id)

        try:
            stars   = "⭐" * payload.rating
            preview = payload.comment[:100] + ("..." if len(payload.comment) > 100 else "")
            await _get_notif().create_notification(
                employee_id = str(payload.receiver_id),
                title       = f"You received a {payload.rating}-star review {stars}",
                message     = (
                    f"{current_user.email} reviewed you ({joined_codes}): \"{preview}\"\n"
                    f"Points earned: {round(pts.raw_points, 1)}"
                ),
                type = NotificationType.REVIEW,
            )
        except Exception:
            logger.exception("Notification failed for review %s", review.review_id)

        # Build response directly from tag_snapshots — no extra DB round trip needed
        final_tags_data = [
            type("Tag", (), {
                "category_id":            s["category_id"],
                "category_code_snapshot": s["category_code_snapshot"],
                "multiplier_snapshot":    s["multiplier_snapshot"],
            })()
            for s in tag_snapshots
        ]
        return _build_review_dict(review, final_tags_data)

    # =========================================================
    # UPDATE REVIEW  — invalidates both parties' caches
    # =========================================================
    @staticmethod
    async def update_review(
        review_id: str,
        payload: ReviewUpdateRequest,
        current_user: CurrentUser,
    ):
        review = await db.reviews.find_unique(where={"review_id": review_id})

        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = review.reviewer_id == current_user.id

        if not is_admin and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to update this review",
            )

        update_data: dict = {}
        if payload.rating    is not None: update_data["rating"]    = payload.rating
        if payload.comment   is not None: update_data["comment"]   = payload.comment
        if payload.image_url is not None: update_data["image_url"] = str(payload.image_url)
        if payload.video_url is not None: update_data["video_url"] = str(payload.video_url)

        if not update_data and payload.category_ids is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        points_changed = payload.rating is not None or payload.category_ids is not None
        old_raw_points = float(getattr(review, "raw_points", 0) or 0)

        if points_changed:
            new_rating = payload.rating if payload.rating is not None else review.rating

            if payload.category_ids is not None:
                new_cat_ids = [str(cid) for cid in payload.category_ids]
            else:
                existing_tags = await db.review_category_tags.find_many(
                    where={"review_id": review_id}
                )
                new_cat_ids = [t.category_id for t in existing_tags]

            review_dt = getattr(review, "review_at", datetime.now(timezone.utc))

            total_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots = (
                await _resolve_multipliers(
                    category_ids   = new_cat_ids,
                    reviewer_roles = current_user.roles,
                    review_dt      = review_dt,
                )
            )

            joined_codes = ",".join(t["category_code_snapshot"] for t in tag_snapshots)

            pts = calculate_points(
                rating                    = new_rating,
                total_category_multiplier = total_multiplier,
                reviewer_weight           = reviewer_weight,
                seasonal_multiplier       = seasonal_multiplier,
                category_code             = joined_codes,
            )

            new_raw_points = round(pts.raw_points, 4)

            logger.info(
                "Points recalculated on update | review=%s categories=%s "
                "old_raw=%.4f new_raw=%.4f",
                review_id, joined_codes, old_raw_points, new_raw_points,
            )

            update_data.update({"raw_points": new_raw_points})

            if payload.category_ids is not None:
                await db.review_category_tags.delete_many(where={"review_id": review_id})
                for snap in tag_snapshots:
                    await db.review_category_tags.create(
                        data={
                            "review_id":              review_id,
                            "category_id":            snap["category_id"],
                            "multiplier_snapshot":    snap["multiplier_snapshot"],
                            "category_code_snapshot": snap["category_code_snapshot"],
                        }
                    )

            points_delta = new_raw_points - old_raw_points
            if abs(points_delta) > 0.0001:
                try:
                    from src.wallet.service import adjust_wallet_for_review_update
                    wallet_result = await adjust_wallet_for_review_update(
                        review_id    = review_id,
                        delta_points = points_delta,
                        current_user = current_user,
                    )
                    logger.info(
                        "Wallet adjusted | review=%s delta=%.4f new_balance=%d",
                        review_id, points_delta, wallet_result.get("new_balance", 0),
                    )
                except Exception:
                    logger.exception(
                        "Wallet adjustment failed for review %s (delta=%.4f)",
                        review_id, points_delta,
                    )

        update_data["updated_at"] = datetime.now(timezone.utc)
        update_data["updated_by"] = current_user.id

        updated = await db.reviews.update(
            where={"review_id": review_id},
            data=update_data,
        )

        # Invalidate both parties' caches
        await invalidate_reviews(review.reviewer_id)
        await invalidate_reviews(review.receiver_id)

        tags = await db.review_category_tags.find_many(
            where={"review_id": review_id},
            order={"created_at": "asc"},
        )
        return _build_review_dict(updated, tags)