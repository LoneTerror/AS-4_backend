import logging
import math
from datetime import datetime, timezone
from fastapi import HTTPException, status

from src.prisma.client import db
from src.recognition.dependencies import CurrentUser
from src.recognition.schemas import ReviewCreateRequest, ReviewUpdateRequest
from src.recognition.points_engine import calculate_points
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType

logger = logging.getLogger(__name__)
_notif = NotificationService(db)

# ─────────────────────────────────────────────────────────────────────────────
# Role priority used when resolving reviewer_weight from the roles table.
# ─────────────────────────────────────────────────────────────────────────────
_ROLE_PRIORITY = ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_review_dict(review, tags: list) -> dict:
    """
    Merge a DB review object with its category tags into a plain dict
    that matches ReviewResponse.

    tags: list of review_category_tags rows (already fetched with the review).
    """
    try:
        data = {k: v for k, v in vars(review).items() if not k.startswith("_")}
    except TypeError:
        data = {col: getattr(review, col) for col in review.__fields__}

    # Build the authoritative tag list from the junction table rows
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
    """Fetch a review row together with its category tags in two parallel-ish queries."""
    review = await db.reviews.find_unique(where={"review_id": review_id})
    if not review:
        return None, []
    tags = await db.review_category_tags.find_many(
        where={"review_id": review_id},
        order={"created_at": "asc"},
    )
    return review, tags


async def _resolve_multipliers(
    category_ids: list[str],
    reviewer_roles: list[str],
    review_dt: datetime,
) -> tuple[float, float, float, list[dict]]:
    """
    Validate each category and resolve all multipliers needed for points calc.

    Returns
    -------
    (total_category_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots)

    tag_snapshots is a list of dicts ready for bulk-insert into review_category_tags.
    """
    if not category_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one category must be provided",
        )

    # ── 1. Fetch & validate each category ────────────────────────────────────
    tag_snapshots  = []
    multipliers    = []

    for cid in category_ids:
        row = await db.review_categories.find_unique(where={"category_id": cid})
        if not row:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Review category not found: {cid}",
            )
        if not row.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Review category is not active: {row.category_code}",
            )
        m = float(row.multiplier)
        multipliers.append(m)
        tag_snapshots.append({
            "category_id":           cid,
            "multiplier_snapshot":   m,
            "category_code_snapshot": row.category_code,
        })

    total_multiplier = sum(multipliers)

    # ── 2. Reviewer weight ────────────────────────────────────────────────────
    reviewer_weight = 1.0
    for role_code in _ROLE_PRIORITY:
        if role_code in reviewer_roles:
            role_row = await db.roles.find_first(where={"role_code": role_code})
            if role_row:
                reviewer_weight = float(role_row.reviewer_weight)
            break

    # ── 3. Seasonal multiplier ────────────────────────────────────────────────
    quarter = (review_dt.month - 1) // 3 + 1

    if review_dt.tzinfo is None:
        review_dt = review_dt.replace(tzinfo=timezone.utc)

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
    seasonal_multiplier = float(seasonal_row.multiplier) if seasonal_row else 1.0

    return total_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots


async def _get_team_member_count(department_id: str | None) -> int:
    where: dict = {
        "status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}
    }
    if department_id:
        where["department_id"] = department_id
    count = await db.employees.count(where=where)
    return max(0, count - 1)


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class RecognitionService:

    # =========================================================
    # LIST REVIEWS
    # =========================================================
    @staticmethod
    async def list_reviews(page: int, limit: int, current_user: CurrentUser):
        skip  = (page - 1) * limit
        where = {}

        if not any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"]):
            where["OR"] = [
                {"reviewer_id": current_user.id},
                {"receiver_id": current_user.id},
            ]

        total   = await db.reviews.count(where=where)
        reviews = await db.reviews.find_many(
            where=where,
            skip=skip,
            take=limit,
            order={"review_at": "desc"},
            include={"review_category_tags": True},
        )
        total_pages = math.ceil(total / limit) if total > 0 else 0

        return {
            "data": [
                _build_review_dict(r, getattr(r, "review_category_tags", []))
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

    # =========================================================
    # GET REVIEW
    # =========================================================
    @staticmethod
    async def get_review(review_id: str, current_user: CurrentUser):
        review = await db.reviews.find_unique(
            where={"review_id": review_id},
            include={"review_category_tags": True},
        )

        if not review:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = review.reviewer_id == current_user.id or review.receiver_id == current_user.id

        if not is_admin and not is_owner:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        return _build_review_dict(review, getattr(review, "review_category_tags", []))

    # =========================================================
    # LIST REVIEW CATEGORIES
    # =========================================================
    @staticmethod
    async def list_review_categories(page: int, limit: int, active_only: bool = True):
        skip  = (page - 1) * limit
        where = {"is_active": True} if active_only else {}

        total      = await db.review_categories.count(where=where)
        categories = await db.review_categories.find_many(
            where=where, skip=skip, take=limit, order={"category_name": "asc"}
        )
        total_pages = math.ceil(total / limit) if total > 0 else 0

        return {
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

    # =========================================================
    # CREATE REVIEW
    # =========================================================
    @staticmethod
    async def create_review(payload: ReviewCreateRequest, current_user: CurrentUser):

        # ── [1] Self-review guard ──────────────────────────────────────────
        if str(payload.receiver_id) == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Self review not allowed",
            )

        # ── [2] Reviewer must be active ────────────────────────────────────
        reviewer = await db.employees.find_unique(
            where={"employee_id": current_user.id},
            include={"status_master_employees_status_idTostatus_master": True},
        )
        if not reviewer or (
            not reviewer.status_master_employees_status_idTostatus_master
            or reviewer.status_master_employees_status_idTostatus_master.status_code != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is not active and cannot submit reviews",
            )

        # ── [3] Receiver must exist and be active ──────────────────────────
        receiver = await db.employees.find_unique(
            where={"employee_id": str(payload.receiver_id)},
            include={"status_master_employees_status_idTostatus_master": True},
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

        now         = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── [4] Duplicate-pair guard (one review per receiver per month) ───
        already_reviewed = await db.reviews.find_first(
            where={
                "reviewer_id": current_user.id,
                "receiver_id": str(payload.receiver_id),
                "review_at":   {"gte": month_start},
            }
        )
        if already_reviewed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="You have already reviewed this person this month",
            )

        # ── [5] Monthly quota ──────────────────────────────────────────────
        is_privileged = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        if not is_privileged:
            monthly_quota = await _get_team_member_count(current_user.department_id)
            if monthly_quota == 0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No active team members found to review",
                )
            monthly_given = await db.reviews.count(
                where={"reviewer_id": current_user.id, "review_at": {"gte": month_start}}
            )
            if monthly_given >= monthly_quota:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Monthly review limit reached ({monthly_given}/{monthly_quota}). "
                        "Your quota equals the number of active teammates in your department."
                    ),
                )

        # ── [6] Resolve REVIEW_ACTIVE status ──────────────────────────────
        review_status = await db.status_master.find_first(
            where={"entity_type": "REVIEW", "status_code": "REVIEW_ACTIVE"}
        )
        if not review_status:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Review status configuration missing",
            )

        # ── [7] Resolve multipliers + build tag snapshots ──────────────────
        category_ids_str = [str(cid) for cid in payload.category_ids]

        total_multiplier, reviewer_weight, seasonal_multiplier, tag_snapshots = (
            await _resolve_multipliers(
                category_ids   = category_ids_str,
                reviewer_roles = current_user.roles,
                review_dt      = now,
            )
        )

        # ── [8] Calculate points ───────────────────────────────────────────
        # formula: rating × sum(category_multipliers) × reviewer_weight × seasonal_multiplier
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

        # ── [9] Write review row ───────────────────────────────────────────
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

        # ── [10] Write junction rows (one per tag) ─────────────────────────
        for snap in tag_snapshots:
            await db.review_category_tags.create(
                data={
                    "review_id":              review.review_id,
                    "category_id":            snap["category_id"],
                    "multiplier_snapshot":    snap["multiplier_snapshot"],
                    "category_code_snapshot": snap["category_code_snapshot"],
                }
            )

        # ── [11] Auto-credit wallet ────────────────────────────────────────
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

        # ── [12] Notify receiver ───────────────────────────────────────────
        try:
            stars   = "⭐" * payload.rating
            preview = payload.comment[:100] + ("..." if len(payload.comment) > 100 else "")
            await _notif.create_notification(
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

        # Return the review enriched with tag data
        tags = await db.review_category_tags.find_many(
            where={"review_id": review.review_id},
            order={"created_at": "asc"},
        )
        return _build_review_dict(review, tags)

    # =========================================================
    # UPDATE REVIEW
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

        # ── Recalculate points if rating or categories changed ─────────────
        points_changed = payload.rating is not None or payload.category_ids is not None
        old_raw_points = float(getattr(review, "raw_points", 0) or 0)

        if points_changed:
            new_rating = payload.rating if payload.rating is not None else review.rating

            # Resolve which category IDs to use
            if payload.category_ids is not None:
                new_cat_ids = [str(cid) for cid in payload.category_ids]
            else:
                # Keep existing tags — fetch from junction table
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

            update_data.update({
                "raw_points": new_raw_points,
            })

            # ── Replace junction rows if categories changed ────────────────
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

            # ── Adjust wallet for points delta ─────────────────────────────
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

        tags = await db.review_category_tags.find_many(
            where={"review_id": review_id},
            order={"created_at": "asc"},
        )
        return _build_review_dict(updated, tags)