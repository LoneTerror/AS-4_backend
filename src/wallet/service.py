import logging
from fastapi import HTTPException, status
from prisma.errors import UniqueViolationError
from src.prisma.client import db
from datetime import datetime, timezone
from src.wallet.dependencies import CurrentUser
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType

# ── Points engine import ───────────────────────────────────────────────────────
# ReviewCategory was removed when multipliers moved to the DB.
# Only the pure calculation helpers are still needed here (legacy fallback path).
from src.recognition.points_engine import (
    calculate_points,
    quarters_elapsed,
    apply_decay,
)

logger = logging.getLogger(__name__)
_notif = NotificationService(db)


logger = setup_logger(__name__)

# -----------------------------
# Utility
# -----------------------------

WNF = "Wallet not found"
AD  = "Access Denied"


def is_admin(user: CurrentUser) -> bool:
    return any(role in user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])


# -----------------------------
# Transaction creation
# -----------------------------

async def create_transaction(data, current_user: CurrentUser):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create transactions"
        )

    wallet_id   = str(data.wallet_id)
    txn_type_id = str(data.transaction_type_id)
    created_by  = current_user.id
    amount      = data.amount

    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero"
        )

    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    txn_type = await db.transaction_types.find_unique(where={"type_id": txn_type_id})
    if not txn_type:
        raise HTTPException(status_code=404, detail="Transaction type not found")

    success_status = await db.status_master.find_first(
        where={"status_code": "APPROVED"}
    )
    if not success_status:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="APPROVED status not found in status_master. Run seed_transaction_types.py"
        )

    status_id = success_status.status_id

    # Debit check
    if not txn_type.is_credit and wallet.available_points < amount:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    new_available = wallet.available_points
    new_redeemed  = wallet.redeemed_points
    new_total     = wallet.total_earned_points

    if txn_type.is_credit:
        new_available += amount
        new_total     += amount
    else:
        new_available -= amount
        new_redeemed  += amount

    try:
        async with db.tx() as transaction:
            new_txn = await transaction.transactions.create(
                data={
                    "wallet_id":          wallet_id,
                    "amount":             amount,
                    "transaction_type_id": txn_type_id,
                    "status_id":          status_id,
                    "description":        data.description,
                    "reference_number":   data.reference_number,
                    "created_by":         created_by,
                    "updated_by":         created_by,
                    "created_at":         datetime.now(timezone.utc),
                    "updated_at":         datetime.now(timezone.utc),
                }
            )

            result = await transaction.wallets.update_many(
                where={"wallet_id": wallet_id, "version": wallet.version},
                data={
                    "available_points":   new_available,
                    "redeemed_points":    new_redeemed,
                    "total_earned_points": new_total,
                    "version":            wallet.version + 1,
                    "updated_by":         created_by,
                }
            )

            if result == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Wallet was updated by another transaction."
                )

        # ── Notify wallet owner ────────────────────────────────────────────
        try:
            direction = "credited to" if txn_type.is_credit else "debited from"
            emoji     = "💰" if txn_type.is_credit else "💸"
            await _notif.create_notification(
                employee_id = wallet.employee_id,
                title       = f"{amount} points {direction} your wallet {emoji}",
                message     = (
                    f"{amount} points have been {direction} your wallet "
                    f"via {txn_type.type_name}."
                    + (f" — {data.description}" if data.description else "")
                    + (f" (Ref: {data.reference_number})" if data.reference_number else "")
                ),
                type = NotificationType.REWARD,
            )
        except Exception:
            logger.exception(
                "Transaction notification failed for txn %s — transaction was saved successfully",
                new_txn.transaction_id,
            )

        final_txn = await db.transactions.find_unique(
            where={"transaction_id": new_txn.transaction_id},
            include={"status_master": True, "transaction_types": True}
        )
        return final_txn

    except UniqueViolationError:
        raise HTTPException(
            status_code=409,
            detail="Transaction with this reference number already exists"
        )


# -----------------------------
# Transaction queries
# -----------------------------

async def get_transactions(
    wallet_id: str,
    page: int,
    limit: int,
    current_user: CurrentUser,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    status_code: str | None = None,
):
    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)

    if not is_admin(current_user) and wallet.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)

    page  = max(page, 1)
    limit = min(max(limit, 1), 100)
    skip  = (page - 1) * limit

    where_clause: dict = {"wallet_id": wallet_id}

    if start_date or end_date:
        where_clause["transaction_at"] = {}
        if start_date:
            where_clause["transaction_at"]["gte"] = start_date
        if end_date:
            where_clause["transaction_at"]["lte"] = end_date

    if status_code:
        status_record = await db.status_master.find_unique(
            where={"status_code": status_code.upper()}
        )
        if status_record:
            where_clause["status_id"] = status_record.status_id

    transactions = await db.transactions.find_many(
        where=where_clause,
        skip=skip,
        take=limit,
        order={"transaction_at": "desc"},
        include={"status_master": True, "transaction_types": True},
    )

    total = await db.transactions.count(where=where_clause)

    formatted = []
    for txn in transactions:
        formatted.append({
            "transaction_id":   txn.transaction_id,
            "wallet_id":        txn.wallet_id,
            "amount":           txn.amount,
            "status": {
                "status_id": str(txn.status_master.status_id),
                "code":      txn.status_master.status_code,
                "name":      txn.status_master.status_name,
            },
            "transaction_type": {
                "type_id":   str(txn.transaction_types.type_id),
                "code":      txn.transaction_types.type_code,
                "name":      txn.transaction_types.type_name,
                "is_credit": txn.transaction_types.is_credit,
            },
            "reference_number": txn.reference_number,
            "description":      txn.description,
            "transaction_at":   txn.transaction_at,
            "created_at":       txn.created_at,
            "updated_at":       txn.updated_at,
            "created_by":       txn.created_by,
            "updated_by":       txn.updated_by,
        })

    return {"page": page, "limit": limit, "total": total, "transactions": formatted}


async def get_transaction_by_id(transaction_id: str, current_user: CurrentUser):
    from src.wallet.schemas import StatusInfo, TransactionTypeInfo

    txn = await db.transactions.find_unique(
        where={"transaction_id": transaction_id},
        include={"status_master": True, "transaction_types": True},
    )

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not is_admin(current_user):
        wallet = await db.wallets.find_unique(where={"wallet_id": txn.wallet_id})
        if not wallet or wallet.employee_id != current_user.id:
            raise HTTPException(status_code=403, detail=AD)

    return {
        "transaction_id":   txn.transaction_id,
        "wallet_id":        txn.wallet_id,
        "amount":           txn.amount,
        "status":           StatusInfo.from_db(txn.status_master),
        "transaction_type": TransactionTypeInfo.from_db(txn.transaction_types),
        "reference_number": txn.reference_number,
        "description":      txn.description,
        "transaction_at":   txn.transaction_at,
        "created_at":       txn.created_at,
        "updated_at":       txn.updated_at,
        "created_by":       txn.created_by,
        "updated_by":       txn.updated_by,
    }


# -----------------------------
# Wallet queries
# -----------------------------

async def get_wallet_by_employee(employee_id: str, current_user: CurrentUser):
    logger.info(
        "Wallet fetch requested for employee_id=%s by user_id=%s",
        employee_id,
        current_user.id
    )
    if not is_admin(current_user) and employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)

    wallet = await db.wallets.find_unique(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return wallet


async def get_wallet_balance(wallet_id: str, current_user: CurrentUser):
    logger.info(
        "Wallet balance fetch requested for wallet_id=%s by user_id=%s",
        wallet_id,
        current_user.id
    )

    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    if not is_admin(current_user) and wallet.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)

    return {
        "wallet_id":        str(wallet.wallet_id),
        "available_points": wallet.available_points,
    }


async def get_points_summary(wallet_id: str, current_user: CurrentUser):
    logger.info(
        "Points summary fetch requested for wallet_id=%s by user_id=%s",
        wallet_id,
        current_user.id
    )
    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    if not is_admin(current_user) and wallet.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)

    now            = datetime.now(timezone.utc)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_of_year  = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    month_txns = await db.transactions.find_many(
        where={"wallet_id": wallet_id, "transaction_at": {"gte": start_of_month}}
    )
    year_txns = await db.transactions.find_many(
        where={"wallet_id": wallet_id, "transaction_at": {"gte": start_of_year}}
    )

    logger.info(
        "Computed summary wallet_id=%s month_txns=%d year_txns=%d",
        wallet_id,
        len(month_txns),
        len(year_txns)
    )
    return {
        "wallet_id":          wallet_id,
        "points_this_month":  sum(t.amount for t in month_txns),
        "points_this_year":   sum(t.amount for t in year_txns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW → WALLET CREDIT  (the key function)
# ─────────────────────────────────────────────────────────────────────────────

async def credit_wallet_from_review(review_id: str, current_user: CurrentUser):
    """
    Credit the receiver's wallet for a review.

    Points formula (via points_engine):
        raw_points = rating × category_multiplier × reviewer_weight × seasonal_multiplier

    The integer part of raw_points is credited to the wallet.
    Idempotent: a UniqueViolationError on reference_number means already credited.
    """
    review_id = str(review_id)

    # ── 1. Fetch the review ───────────────────────────────────────────────
    review = await db.reviews.find_unique(where={"review_id": review_id})
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")

    employee_id = review.receiver_id
    created_by  = review.created_by

    # ── 2. Resolve points ─────────────────────────────────────────────────
    #
    # Happy path: use pre-computed raw_points stored on the review row.
    # Legacy path: recalculate using multipliers stored on the review row,
    #              falling back to 1.0 defaults if they were never stored.
    #
    if review.raw_points is not None:
        points = max(1, round(review.raw_points))
        breakdown = {
            "source":              "stored",
            "raw_points":          review.raw_points,
            "category":            review.category,
            "category_multiplier": review.category_multiplier,
            "reviewer_weight":     review.reviewer_weight,
            "seasonal_multiplier": review.seasonal_multiplier,
        }
    else:
        # Legacy review — recalculate with the new engine signature.
        # All multipliers are read from the review row itself; if absent,
        # default to 1.0 (neutral) so the rating alone determines points.
        logger.warning(
            "review %s has no raw_points — recalculating with defaults", review_id
        )
        category_multiplier = float(review.category_multiplier or 1.0)
        reviewer_weight     = float(review.reviewer_weight     or 1.0)
        seasonal_multiplier = float(review.seasonal_multiplier or 1.0)
        decay_rate          = 0.9   # sensible default; ideally read from points_config
        review_dt           = review.review_at or datetime.now(timezone.utc)

        pts = calculate_points(
            rating              = review.rating,
            category_multiplier = category_multiplier,
            reviewer_weight     = reviewer_weight,
            seasonal_multiplier = seasonal_multiplier,
            decay_rate          = decay_rate,
            review_dt           = review_dt,
            category_code       = review.category or "UNKNOWN",
        )
        points    = max(1, round(pts.raw_points))
        breakdown = pts.as_dict()
        breakdown["source"] = "recalculated"

    if points == 0:
        return {"message": "No points awarded for this rating", "credited_points": 0}

    # ── 3. Fetch wallet ───────────────────────────────────────────────────
    wallet = await db.wallets.find_unique(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=WNF)

    # ── 4. Resolve CREDIT transaction type ────────────────────────────────
    txn_type = await db.transaction_types.find_unique(where={"type_code": "CREDIT"})
    if not txn_type:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CREDIT transaction type missing. Run seed_transaction_types.py"
        )

    # ── 5. Resolve APPROVED status ────────────────────────────────────────
    status_record = await db.status_master.find_first(where={"status_code": "APPROVED"})
    if not status_record:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="APPROVED status not found in status_master. Run seed_transaction_types.py"
        )

    # ── 6. Idempotent reference — one credit per review, forever ──────────
    reference     = f"REVIEW-{review_id}"
    new_available = wallet.available_points    + points
    new_total     = wallet.total_earned_points + points
    category_label = review.category or "REVIEW"

    try:
        async with db.tx() as txn:
            new_txn = await txn.transactions.create(
                data={
                    "wallet_id":           wallet.wallet_id,
                    "amount":              points,
                    "transaction_type_id": txn_type.type_id,
                    "status_id":           status_record.status_id,
                    "description":         (
                        f"{review.rating}★ {category_label} review "
                        f"→ {points} pts "
                        f"(×{review.category_multiplier or 1.0} cat, "
                        f"×{review.reviewer_weight or 1.0} role, "
                        f"×{review.seasonal_multiplier or 1.0} seasonal)"
                    ),
                    "reference_number":    reference,
                    "created_by":          created_by,
                    "updated_by":          created_by,
                    "created_at":          datetime.now(timezone.utc),
                    "updated_at":          datetime.now(timezone.utc),
                }
            )

            result = await txn.wallets.update_many(
                where={"wallet_id": wallet.wallet_id, "version": wallet.version},
                data={
                    "available_points":    new_available,
                    "total_earned_points": new_total,
                    "version":             wallet.version + 1,
                    "updated_by":          created_by,
                }
            )

            if result == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Wallet updated concurrently — please retry"
                )

        # ── Notify receiver (non-blocking) ────────────────────────────────
        try:
            stars = "⭐" * review.rating
            await _notif.create_notification(
                employee_id = employee_id,
                title       = f"{points} points credited to your wallet 💰",
                message     = (
                    f"You earned {points} pts for a {review.rating}-star "
                    f"{category_label} review {stars}. "
                    f"New balance: {new_available} pts."
                ),
                type = NotificationType.REWARD,
            )
        except Exception:
            logger.exception(
                "Credit notification failed for review %s — points were credited successfully",
                review_id,
            )

        logger.info(
            "Wallet credited | employee=%s review=%s points=%d "
            "available=%d total=%d breakdown=%s",
            employee_id, review_id, points, new_available, new_total, breakdown,
        )

        return {
            "transaction_id":  str(new_txn.transaction_id),
            "wallet_id":       str(wallet.wallet_id),
            "credited_points": points,
            "new_balance":     new_available,
            "breakdown":       breakdown,
            "message":         f"{points} points credited successfully",
        }

    except UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Points already credited for this review"
        )


async def get_transaction_types(current_user: CurrentUser):
    if not is_admin(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=AD)

    types = await db.transaction_types.find_many()

    return [
        {
            "type_id":   str(t.type_id),
            "code":      t.type_code,
            "name":      t.type_name,
            "is_credit": t.is_credit,
        }
        for t in types
    ]