import logging
import math
from datetime import datetime, timezone
from fastapi import HTTPException, status

from src.prisma.client import db
from src.recognition.dependencies import CurrentUser
from src.recognition.schemas import ReviewCreateRequest, ReviewUpdateRequest
from src.recognition.points_engine import (
    calculate_points,
    quarters_elapsed,
    apply_decay,
)
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType

logger = logging.getLogger(__name__)
_notif = NotificationService(db)

# ─────────────────────────────────────────────────────────────────────────────
# Role priority used when resolving reviewer_weight from the roles table.
# Higher-privilege roles take precedence.
# ─────────────────────────────────────────────────────────────────────────────
_ROLE_PRIORITY = ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"]

# Fallback decay rate used if points_config row is missing (keeps service alive
# even if the seed migration hasn't run yet).
_FALLBACK_DECAY_RATE = 0.9


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _enrich_with_effective_points(review, decay_rate: float | None = None) -> dict:
    """
    Given a DB review object, recalculate effective_points using the stored
    raw_points and the review's review_at timestamp.

    Returns a plain dict so the router can construct ReviewResponse from it.
    Decay is recomputed on every read — cheap (pure math, no DB call).

    decay_rate: pass the live value resolved from points_config when available
    (e.g. immediately after create/update). Falls back to _FALLBACK_DECAY_RATE
    for list/get reads where we skip the extra DB call.
    NOTE: decay_rate is NOT a column on the reviews table (schema has no such
    field), so it is never written to the DB — only used for in-memory calc.

    FIX: Uses vars() instead of review.__fields__ which is fragile across
    Prisma client versions.
    """
    # vars() works on Prisma model instances; falls back gracefully
    try:
        data = dict(vars(review))
        # Remove private / internal Prisma attributes
        data = {k: v for k, v in data.items() if not k.startswith("_")}
    except TypeError:
        data = {col: getattr(review, col) for col in review.__fields__}

    raw       = getattr(review, "raw_points", None)
    review_at = getattr(review, "review_at",  None)
    rate      = decay_rate if decay_rate is not None else _FALLBACK_DECAY_RATE

    if raw is not None and review_at is not None:
        q = quarters_elapsed(review_at)
        data["effective_points"] = round(apply_decay(raw, q, rate), 4)
    else:
        data["effective_points"] = None

    return data


async def _resolve_points_inputs(
    category_id: str,
    reviewer_roles: list[str],
    review_dt: datetime,
) -> tuple[float, float, float, float, str]:
    """
    Resolve all four multipliers from the DB for a given review context.

    Returns
    -------
    (category_multiplier, reviewer_weight, seasonal_multiplier, decay_rate, category_code)
    """
    # ── 1. Category multiplier ────────────────────────────────────────────────
    category_row = await db.review_categories.find_unique(
        where={"category_id": category_id}
    )
    if not category_row:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Review category not found",
        )
    if not category_row.is_active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Review category is not active",
        )
    category_multiplier = float(category_row.multiplier)
    category_code       = category_row.category_code

    # ── 2. Reviewer weight (from roles table) ─────────────────────────────────
    reviewer_weight = 1.0   # safe fallback
    for role_code in _ROLE_PRIORITY:
        if role_code in reviewer_roles:
            role_row = await db.roles.find_first(where={"role_code": role_code})
            if role_row:
                reviewer_weight = float(role_row.reviewer_weight)
            break

    # ── 3. Seasonal multiplier ────────────────────────────────────────────────
    quarter = (review_dt.month - 1) // 3 + 1   # 1–4

    # Prisma's Python client requires a full datetime (not datetime.date) for
    # DateTime fields — passing a date object causes a JSON serialization error
    # in prisma._builder.  We keep review_dt as-is (already a UTC datetime).
    # Ensure it's timezone-aware so the lte comparison is unambiguous.
    if review_dt.tzinfo is None:
        review_dt = review_dt.replace(tzinfo=timezone.utc)

    # Most recently effective row for this quarter wins.
    # effective_from IS NULL rows are treated as always-active baselines.
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

    # ── 4. Decay rate ─────────────────────────────────────────────────────────
    decay_row = await db.points_config.find_first(
        where={"config_key": "DECAY_RATE"}
    )
    decay_rate = float(decay_row.config_value) if decay_row else _FALLBACK_DECAY_RATE

    return category_multiplier, reviewer_weight, seasonal_multiplier, decay_rate, category_code


async def _get_team_member_count(department_id: str | None) -> int:
    """
    Returns the number of ACTIVE employees in the reviewer's department,
    excluding the reviewer themselves (they can't review themselves anyway,
    but we want the count of people they *could* review).

    If the reviewer has no department_id (e.g. SUPER_ADMIN), falls back to
    counting all active employees — effectively no meaningful cap.

    The result is used as the monthly review quota:
        quota = number of active team members in the department
    This means a reviewer can give at most one review per teammate per month,
    which is also enforced separately by the duplicate-pair guard.
    """
    where: dict = {"status_master_employees_status_idTostatus_master": {"status_code": "ACTIVE"}}

    if department_id:
        where["department_id"] = department_id

    count = await db.employees.count(where=where)
    # Subtract 1 to exclude the reviewer themselves
    return max(0, count - 1)


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE
# ─────────────────────────────────────────────────────────────────────────────

class RecognitionService:
    """
    Service layer for review management.

    Responsibilities:
    - Business rule enforcement (self-review, active reviewer + receiver, etc.)
    - Monthly review quota derived from team size (1 review per teammate/month)
    - Duplicate-pair guard (same reviewer → same receiver only once per month)
    - RBAC access control
    - Points calculation (via points_engine — all multipliers from DB)
    - Decay rate snapshot stored on review row for reproducible decay reads
    - Wallet crediting + adjustment on update
    - Pagination logic
    - Audit field handling
    """

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
        )
        total_pages = math.ceil(total / limit) if total > 0 else 0

        return {
            "data": [_enrich_with_effective_points(r) for r in reviews],
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
        review = await db.reviews.find_unique(where={"review_id": review_id})

        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found",
            )

        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = (
            review.reviewer_id == current_user.id
            or review.receiver_id == current_user.id
        )

        if not is_admin and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return _enrich_with_effective_points(review)

    # =========================================================
    # LIST REVIEW CATEGORIES
    # =========================================================
    @staticmethod
    async def list_review_categories(page: int, limit: int, active_only: bool = True):
        """
        Return paginated review categories so clients can build a category picker.
        Only ACTIVE categories are returned by default.
        """
        skip  = (page - 1) * limit
        where = {"is_active": True} if active_only else {}

        total      = await db.review_categories.count(where=where)
        categories = await db.review_categories.find_many(
            where=where,
            skip=skip,
            take=limit,
            order={"category_name": "asc"},
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

        # ── [1] Self-review protection ─────────────────────────────────────
        if str(payload.receiver_id) == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Self review not allowed",
            )

        # ── [2] Reviewer must be an active employee ────────────────────────
        # Prevents deactivated accounts with valid JWTs from submitting reviews.
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

        # ── [3] Validate receiver existence + ACTIVE status ────────────────
        receiver = await db.employees.find_unique(
            where={"employee_id": str(payload.receiver_id)},
            include={"status_master_employees_status_idTostatus_master": True},
        )

        if not receiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receiver not found",
            )

        if (
            not receiver.status_master_employees_status_idTostatus_master
            or receiver.status_master_employees_status_idTostatus_master.status_code != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Receiver is not active",
            )

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── [4] Duplicate-pair guard ───────────────────────────────────────
        # One reviewer may review the same person only once per calendar month.
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

        # ── [5] Monthly quota = number of active teammates ─────────────────
        # Team size is the count of active employees in the reviewer's
        # department (excluding the reviewer).  A reviewer can give at most
        # one review per teammate, so quota == team size makes this natural.
        # HR_ADMIN and SUPER_ADMIN bypass the quota entirely.
        is_privileged = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        if not is_privileged:
            monthly_quota = await _get_team_member_count(current_user.department_id)

            if monthly_quota == 0:
                # Edge case: reviewer has no teammates yet — block generously
                # rather than allowing unlimited reviews.
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="No active team members found to review",
                )

            monthly_given = await db.reviews.count(
                where={
                    "reviewer_id": current_user.id,
                    "review_at":   {"gte": month_start},
                }
            )

            if monthly_given >= monthly_quota:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Monthly review limit reached ({monthly_given}/{monthly_quota}). "
                        f"Your quota equals the number of active teammates in your department."
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

        # ── [7] Resolve all multipliers from the DB ────────────────────────
        (
            category_multiplier,
            reviewer_weight,
            seasonal_multiplier,
            decay_rate,
            category_code,
        ) = await _resolve_points_inputs(
            category_id    = str(payload.category_id),
            reviewer_roles = current_user.roles,
            review_dt      = now,
        )

        # ── [8] Calculate points ───────────────────────────────────────────
        pts = calculate_points(
            rating               = payload.rating,
            category_multiplier  = category_multiplier,
            reviewer_weight      = reviewer_weight,
            seasonal_multiplier  = seasonal_multiplier,
            decay_rate           = decay_rate,
            review_dt            = now,
            category_code        = category_code,
        )

        logger.info(
            "Points calculated | receiver=%s rating=%s category=%s "
            "raw=%.4f effective=%.4f reviewer_roles=%s",
            payload.receiver_id, payload.rating, category_code,
            pts.raw_points, pts.effective_points, current_user.roles,
        )

        # ── [9] Write review row ───────────────────────────────────────────
        review = await db.reviews.create(
            data={
                "reviewer_id":         current_user.id,
                "receiver_id":         str(payload.receiver_id),
                "rating":              payload.rating,
                "comment":             payload.comment,
                # FK to review_categories
                "category_id":         str(payload.category_id),
                # Denormalised snapshot so reads don't need a JOIN
                "category_code":       category_code,
                "image_url":           str(payload.image_url) if payload.image_url else None,
                "video_url":           str(payload.video_url) if payload.video_url else None,
                "status_id":           review_status.status_id,
                "review_at":           now,
                "created_at":          now,
                "created_by":          current_user.id,
                "updated_at":          now,
                "updated_by":          current_user.id,
                # ── Points snapshot — frozen at creation time ────────────
                # Stored so historical calculations are reproducible even if
                # an admin later changes a multiplier in the DB.
                "raw_points":          round(pts.raw_points, 4),
                "category_multiplier": pts.category_multiplier,
                "reviewer_weight":     pts.reviewer_weight,
                "seasonal_multiplier": pts.seasonal_multiplier,
                # NOTE: decay_rate is NOT persisted (no column in schema).
                # It is passed to _enrich_with_effective_points below so that
                # the response uses the live rate rather than the fallback.
            }
        )

        # ── [10] AUTO-CREDIT WALLET ────────────────────────────────────────
        try:
            from src.wallet.service import credit_wallet_from_review
            wallet_result = await credit_wallet_from_review(
                review_id    = review.review_id,
                current_user = current_user,
            )
            logger.info(
                "Wallet credited automatically | review=%s credited=%d new_balance=%d",
                review.review_id,
                wallet_result.get("credited_points", 0),
                wallet_result.get("new_balance", 0),
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                logger.info("Wallet already credited for review %s — skipping", review.review_id)
            else:
                logger.exception(
                    "Wallet credit failed for review %s (status %s) — review was saved",
                    review.review_id, exc.status_code,
                )
        except Exception:
            logger.exception(
                "Unexpected wallet credit failure for review %s — review was saved",
                review.review_id,
            )

        # ── [11] Notify receiver (non-blocking) ───────────────────────────
        try:
            stars   = "⭐" * payload.rating
            preview = payload.comment[:100] + ("..." if len(payload.comment) > 100 else "")
            await _notif.create_notification(
                employee_id = str(payload.receiver_id),
                title       = f"You received a {payload.rating}-star review {stars}",
                message     = (
                    f"{current_user.email} reviewed you ({category_code}): \"{preview}\"\n"
                    f"Points earned: {round(pts.raw_points, 1)}"
                ),
                type = NotificationType.REVIEW,
            )
        except Exception:
            logger.exception(
                "Notification failed for review %s — review was saved successfully",
                review.review_id,
            )

        return _enrich_with_effective_points(review, decay_rate=decay_rate)

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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found",
            )

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

        if not update_data and payload.category_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update",
            )

        # ── Recalculate points if rating or category changed ───────────────
        points_changed = payload.rating is not None or payload.category_id is not None
        old_raw_points = float(getattr(review, "raw_points", 0) or 0)

        if points_changed:
            new_rating      = payload.rating if payload.rating is not None else review.rating
            new_category_id = (
                str(payload.category_id)
                if payload.category_id is not None
                else review.category_id
            )

            # Preserve original review_at for seasonal multiplier so the
            # seasonal boost matches the period the review was actually written.
            review_dt = getattr(review, "review_at", datetime.now(timezone.utc))

            (
                category_multiplier,
                reviewer_weight,
                seasonal_multiplier,
                decay_rate,
                category_code,
            ) = await _resolve_points_inputs(
                category_id    = new_category_id,
                reviewer_roles = current_user.roles,
                review_dt      = review_dt,
            )

            pts = calculate_points(
                rating               = new_rating,
                category_multiplier  = category_multiplier,
                reviewer_weight      = reviewer_weight,
                seasonal_multiplier  = seasonal_multiplier,
                decay_rate           = decay_rate,
                review_dt            = review_dt,
                category_code        = category_code,
            )

            new_raw_points = round(pts.raw_points, 4)

            logger.info(
                "Points recalculated on update | review=%s old_raw=%.4f new_raw=%.4f",
                review_id, old_raw_points, new_raw_points,
            )

            update_data["category_id"]         = new_category_id
            update_data["category_code"]        = category_code
            update_data["raw_points"]           = new_raw_points
            update_data["category_multiplier"]  = pts.category_multiplier
            update_data["reviewer_weight"]      = pts.reviewer_weight
            update_data["seasonal_multiplier"]  = pts.seasonal_multiplier
            # decay_rate not written to DB (no column); kept in local var
            # for passing to _enrich_with_effective_points below.

            # ── FIX: Adjust wallet for the points delta ────────────────────
            # When rating or category changes the receiver's wallet must be
            # adjusted by (new_raw_points - old_raw_points).  We do this
            # non-fatally: a failure is logged but does not roll back the
            # review update, keeping reviews and wallets eventually consistent.
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
                        "Wallet adjusted for review update | review=%s delta=%.4f new_balance=%d",
                        review_id,
                        points_delta,
                        wallet_result.get("new_balance", 0),
                    )
                except Exception:
                    logger.exception(
                        "Wallet adjustment failed for review update %s (delta=%.4f) — "
                        "review was updated, wallet may be stale",
                        review_id, points_delta,
                    )

        update_data["updated_at"] = datetime.now(timezone.utc)
        update_data["updated_by"] = current_user.id

        updated = await db.reviews.update(
            where={"review_id": review_id},
            data=update_data,
        )

        return _enrich_with_effective_points(updated, decay_rate=decay_rate if points_changed else None)