# src/wallet/service.py
import logging
from typing import Optional
from fastapi import HTTPException, Request, status
from prisma.errors import UniqueViolationError
from src.prisma.client import db
from datetime import datetime, timezone
from src.common.audit import audit_ctx, audit
from src.common.dependencies import CurrentUser
from src.common.cache import (
    cache_get, cache_set, cache_delete, invalidate_pattern,
    TTL_VOLATILE,  L1_VOLATILE,
    TTL_PERMANENT, L1_PERMANENT,
)
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


# ── Cache keys ────────────────────────────────────────────────────────────────
_KEY_TXN_TYPES = "wallet:transaction_types"

def _wallet_key(employee_id: str) -> str:
    return f"wallets:employee:{employee_id}"


WNF = "Wallet not found"
AD  = "Access Denied"


def is_admin(user: CurrentUser) -> bool:
    return any(role in user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])


# ─────────────────────────────────────────────────────────────────────────────
# READ — transaction types
# ─────────────────────────────────────────────────────────────────────────────

async def get_transaction_types(current_user: CurrentUser):
    cached = await cache_get(_KEY_TXN_TYPES, l1_ttl=L1_PERMANENT)
    if cached is not None:
        return cached

    types = await db.transaction_types.find_many()
    data  = [
        {
            "type_id":   str(t.type_id),
            "code":      t.type_code,
            "name":      t.type_name,
            "is_credit": t.is_credit,
        }
        for t in types
    ]
    await cache_set(_KEY_TXN_TYPES, data, ttl=TTL_PERMANENT, l1_ttl=L1_PERMANENT)
    return data


# ─────────────────────────────────────────────────────────────────────────────
# WRITE — manual transaction (HR/admin initiated)
# ─────────────────────────────────────────────────────────────────────────────

async def create_transaction(
    data,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create transactions",
        )

    wallet_id   = str(data.wallet_id)
    txn_type_id = str(data.transaction_type_id)
    created_by  = current_user.id
    amount      = data.amount

    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")

    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)

    txn_type = await db.transaction_types.find_unique(where={"type_id": txn_type_id})
    if not txn_type:
        raise HTTPException(status_code=404, detail="Transaction type not found")

    success_status = await db.status_master.find_first(where={"status_code": "APPROVED"})
    if not success_status:
        raise HTTPException(status_code=500, detail="APPROVED status not found in status_master")

    if not txn_type.is_credit and wallet.available_points < amount:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    new_available = wallet.available_points + amount if txn_type.is_credit else wallet.available_points - amount
    new_redeemed  = wallet.redeemed_points  + (0 if txn_type.is_credit else amount)
    new_total     = wallet.total_earned_points + (amount if txn_type.is_credit else 0)

    new_txn = None
    try:
        async with audit_ctx(
            user_id    = created_by,
            request    = request,
            table_name = "transactions",
            record_id  = lambda: str(new_txn.transaction_id) if new_txn else "",
            operation  = "INSERT",
            new_values = lambda: {
                "wallet_id":        wallet_id,
                "amount":           amount,
                "type_code":        txn_type.type_code,
                "is_credit":        txn_type.is_credit,
                "reference_number": data.reference_number,
            },
        ):
            async with db.tx() as transaction:
                new_txn = await transaction.transactions.create(
                    data={
                        "wallet_id":           wallet_id,
                        "amount":              amount,
                        "transaction_type_id": txn_type_id,
                        "status_id":           success_status.status_id,
                        "description":         data.description,
                        "reference_number":    data.reference_number,
                        "created_by":          created_by,
                        "updated_by":          created_by,
                        "created_at":          datetime.now(timezone.utc),
                        "updated_at":          datetime.now(timezone.utc),
                    }
                )

                result = await transaction.wallets.update_many(
                    where={"wallet_id": wallet_id, "version": wallet.version},
                    data={
                        "available_points":    new_available,
                        "redeemed_points":     new_redeemed,
                        "total_earned_points": new_total,
                        "version":             wallet.version + 1,
                        "updated_by":          created_by,
                    },
                )

                if result == 0:
                    raise HTTPException(status_code=409,
                                        detail="Wallet was updated by another transaction.")

        await cache_delete(_wallet_key(wallet.employee_id))

        try:
            direction = "credited to" if txn_type.is_credit else "debited from"
            await _get_notif().create_notification(
                employee_id=wallet.employee_id,
                title=f"{amount} points {direction} your wallet",
                message=(
                    f"{amount} points have been {direction} your wallet "
                    f"via {txn_type.type_name}."
                    + (f" — {data.description}" if data.description else "")
                    + (f" (Ref: {data.reference_number})" if data.reference_number else "")
                ),
                type=NotificationType.REWARD,
            )
        except Exception:
            logger.exception("Transaction notification failed for txn %s", new_txn.transaction_id)

        final_txn = await db.transactions.find_unique(
            where={"transaction_id": new_txn.transaction_id},
            include={"status_master": True, "transaction_types": True},
        )
        return final_txn

    except UniqueViolationError:
        raise HTTPException(status_code=409,
                            detail="Transaction with this reference number already exists")


# ─────────────────────────────────────────────────────────────────────────────
# READ — transactions list
# ─────────────────────────────────────────────────────────────────────────────

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
        if start_date: where_clause["transaction_at"]["gte"] = start_date
        if end_date:   where_clause["transaction_at"]["lte"] = end_date

    if status_code:
        status_record = await db.status_master.find_unique(
            where={"status_code": status_code.upper()}
        )
        if status_record:
            where_clause["status_id"] = status_record.status_id

    transactions = await db.transactions.find_many(
        where=where_clause, skip=skip, take=limit,
        order={"transaction_at": "desc"},
        include={"status_master": True, "transaction_types": True},
    )
    total = await db.transactions.count(where=where_clause)

    # Dynamically patch legacy descriptions that have raw UUIDs instead of reviewer names
    for txn in transactions:
        desc = txn.description or ""
        if desc.startswith("Points credited from review") and " by " not in desc:
            review_id = txn.reference_number
            if review_id and review_id.startswith("REVIEW-"):
                review_id = review_id.replace("REVIEW-", "")
            if review_id:
                try:
                    review = await db.reviews.find_unique(
                        where={"review_id": review_id},
                        include={"employees_reviews_reviewer_idToemployees": True}
                    )
                    if review and getattr(review, "employees_reviews_reviewer_idToemployees", None):
                        reviewer_name = review.employees_reviews_reviewer_idToemployees.username
                        txn.description = f"Points credited from {reviewer_name}"
                except Exception:
                    pass

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

    desc = txn.description or ""
    if desc.startswith("Points credited from review") and " by " not in desc:
        review_id = txn.reference_number
        if review_id and review_id.startswith("REVIEW-"):
            review_id = review_id.replace("REVIEW-", "")
        if review_id:
            try:
                review = await db.reviews.find_unique(
                    where={"review_id": review_id},
                    include={"employees_reviews_reviewer_idToemployees": True}
                )
                if review and getattr(review, "employees_reviews_reviewer_idToemployees", None):
                    reviewer_name = review.employees_reviews_reviewer_idToemployees.username
                    txn.description = f"Points credited from {reviewer_name}"
            except Exception:
                pass

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


# ─────────────────────────────────────────────────────────────────────────────
# READ — wallet lookups
# ─────────────────────────────────────────────────────────────────────────────

async def get_wallet_by_employee(employee_id: str, current_user: CurrentUser):
    if not is_admin(current_user) and employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)

    key    = _wallet_key(employee_id)
    cached = await cache_get(key, l1_ttl=L1_VOLATILE)
    if cached is not None:
        return cached

    wallet = await db.wallets.find_unique(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)

    data = wallet.model_dump()
    await cache_set(key, data, ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return wallet


async def get_wallet_balance(wallet_id: str, current_user: CurrentUser):
    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)
    if not is_admin(current_user) and wallet.employee_id != current_user.id:
        raise HTTPException(status_code=403, detail=AD)
    return {"wallet_id": str(wallet.wallet_id), "available_points": wallet.available_points}


async def get_points_summary(wallet_id: str, current_user: CurrentUser):
    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)
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

    return {
        "wallet_id":         wallet_id,
        "points_this_month": sum(t.amount for t in month_txns),
        "points_this_year":  sum(t.amount for t in year_txns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# WRITE — credit wallet from review (called by consumer/internal)
# No HTTP request available — request=None, trigger uses sentinel fallback
# for session context but performed_by is set to the reviewer (created_by)
# ─────────────────────────────────────────────────────────────────────────────

async def credit_wallet_from_review(review_id: str, current_user: CurrentUser):
    review = await db.reviews.find_unique(
        where={"review_id": review_id},
        include={"review_category_tags": True},
    )
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    employee_id = review.receiver_id
    created_by  = review.created_by

    if review.raw_points is not None:
        points    = max(1, round(review.raw_points))
        breakdown = {"source": "stored", "raw_points": review.raw_points}
    else:
        logger.error(
            "review %s has no raw_points — recalculation not supported", review_id
        )
        raise HTTPException(
            status_code=422,
            detail=(
                f"Review {review_id} has no raw_points stored and cannot be recalculated. "
                "Re-submit the review to generate raw_points."
            ),
        )

    if points == 0:
        return {"message": "No points awarded for this rating", "credited_points": 0}

    wallet = await db.wallets.find_unique(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)

    txn_type = await db.transaction_types.find_unique(where={"type_code": "CREDIT"})
    if not txn_type:
        raise HTTPException(status_code=500, detail="CREDIT transaction type missing")

    status_record = await db.status_master.find_first(where={"status_code": "APPROVED"})
    if not status_record:
        raise HTTPException(status_code=500, detail="APPROVED status not found")

    reviewer = await db.employees.find_unique(where={"employee_id": created_by})
    reviewer_name = reviewer.username if reviewer else "Anonymous"

    tags           = getattr(review, "review_category_tags", []) or []
    category_label = ",".join(t.category_code_snapshot for t in tags) if tags else "REVIEW"
    reference      = f"REVIEW-{review_id}"
    new_available  = wallet.available_points    + points
    new_total      = wallet.total_earned_points + points

    new_txn = None
    try:
        # No HTTP request here — this is called from a consumer.
        # set_audit_context will use created_by (the reviewer's employee_id)
        # so audit_log.performed_by shows who triggered the credit.
        async with audit_ctx(
            user_id    = str(created_by),
            request    = None,
            table_name = "transactions",
            record_id  = lambda: str(new_txn.transaction_id) if new_txn else "",
            operation  = "CREDIT",
            new_values = lambda: {
                "wallet_id":       str(wallet.wallet_id),
                "employee_id":     str(employee_id),
                "points":          points,
                "review_id":       review_id,
                "category_label":  category_label,
                "reference":       reference,
            },
        ):
            async with db.tx() as txn:
                new_txn = await txn.transactions.create(
                    data={
                        "wallet_id":           wallet.wallet_id,
                        "amount":              points,
                        "transaction_type_id": txn_type.type_id,
                        "status_id":           status_record.status_id,
                        "description":         f"{category_label} from {reviewer_name} → {points} pts",
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
                    },
                )

                if result == 0:
                    raise HTTPException(status_code=409,
                                        detail="Wallet updated concurrently — please retry")

        await cache_delete(_wallet_key(employee_id))

        try:
            await _get_notif().create_notification(
                employee_id=employee_id,
                title=f"{points} points credited to your wallet",
                message=(
                    f"You earned {points} pts for a {category_label} review. "
                    f"New balance: {new_available} pts."
                ),
                type=NotificationType.REWARD,
            )
        except Exception:
            logger.exception("Credit notification failed for review %s", review_id)

        logger.info(
            "Wallet credited | employee=%s review=%s points=%d available=%d total=%d",
            employee_id, review_id, points, new_available, new_total,
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
        raise HTTPException(status_code=409,
                            detail="Points already credited for this review")


# ─────────────────────────────────────────────────────────────────────────────
# WRITE — adjust wallet for review update
# ─────────────────────────────────────────────────────────────────────────────

async def adjust_wallet_for_review_update(
    review_id: str,
    delta_points: float,
    current_user: CurrentUser,
):
    int_delta = round(delta_points)

    if int_delta == 0:
        return {
            "message":         "No wallet adjustment needed (delta rounds to zero)",
            "credited_points": 0,
            "new_balance":     None,
        }

    review = await db.reviews.find_unique(where={"review_id": review_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    employee_id = review.receiver_id
    updated_by  = current_user.id

    wallet = await db.wallets.find_unique(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=404, detail=WNF)

    if int_delta < 0 and wallet.available_points + int_delta < 0:
        logger.warning(
            "Skipping wallet debit for review update %s — would go negative "
            "(available=%d delta=%d)", review_id, wallet.available_points, int_delta,
        )
        return {
            "message":         "Wallet debit skipped — insufficient balance",
            "credited_points": int_delta,
            "new_balance":     wallet.available_points,
        }

    type_code = "CREDIT" if int_delta > 0 else "DEBIT"
    txn_type  = await db.transaction_types.find_unique(where={"type_code": type_code})
    if not txn_type:
        raise HTTPException(status_code=500, detail=f"{type_code} transaction type missing")

    status_record = await db.status_master.find_first(where={"status_code": "APPROVED"})
    if not status_record:
        raise HTTPException(status_code=500, detail="APPROVED status not found")

    abs_delta      = abs(int_delta)
    new_available  = wallet.available_points    + int_delta
    new_total      = wallet.total_earned_points + (int_delta if int_delta > 0 else 0)
    now            = datetime.now(timezone.utc)
    reference      = f"REVIEW-UPDATE-{review_id}-{now.strftime('%Y%m%dT%H%M%S')}"
    direction_word = "adjusted +" if int_delta > 0 else "adjusted "

    new_txn = None
    try:
        async with audit_ctx(
            user_id    = updated_by,
            request    = None,     # internal call — no HTTP context
            table_name = "transactions",
            record_id  = lambda: str(new_txn.transaction_id) if new_txn else "",
            operation  = "ADJUST",
            new_values = lambda: {
                "wallet_id":   str(wallet.wallet_id),
                "employee_id": str(employee_id),
                "delta":       int_delta,
                "review_id":   review_id,
                "reference":   reference,
            },
        ):
            async with db.tx() as txn:
                new_txn = await txn.transactions.create(
                    data={
                        "wallet_id":           wallet.wallet_id,
                        "amount":              abs_delta,
                        "transaction_type_id": txn_type.type_id,
                        "status_id":           status_record.status_id,
                        "description":         (
                            f"Review update → wallet {direction_word}{int_delta:+d} pts "
                            f"(raw delta={delta_points:+.4f})"
                        ),
                        "reference_number": reference,
                        "created_by":       updated_by,
                        "updated_by":       updated_by,
                        "created_at":       now,
                        "updated_at":       now,
                    }
                )

                result = await txn.wallets.update_many(
                    where={"wallet_id": wallet.wallet_id, "version": wallet.version},
                    data={
                        "available_points":    new_available,
                        "total_earned_points": new_total,
                        "version":             wallet.version + 1,
                        "updated_by":          updated_by,
                        "updated_at":          now,
                    },
                )

                if result == 0:
                    raise HTTPException(status_code=409,
                                        detail="Wallet updated concurrently — please retry")

        await cache_delete(_wallet_key(employee_id))

        try:
            emoji = "💰" if int_delta > 0 else "📉"
            await _get_notif().create_notification(
                employee_id=employee_id,
                title=f"Your wallet was adjusted {emoji}",
                message=(
                    f"A review you received was updated. "
                    f"Your wallet was adjusted by {int_delta:+d} pts. "
                    f"New balance: {new_available} pts."
                ),
                type=NotificationType.REWARD,
            )
        except Exception:
            logger.exception("Adjustment notification failed for review update %s", review_id)

        logger.info(
            "Wallet adjusted | employee=%s review=%s delta=%d new_available=%d",
            employee_id, review_id, int_delta, new_available,
        )

        return {
            "transaction_id":  str(new_txn.transaction_id),
            "wallet_id":       str(wallet.wallet_id),
            "credited_points": int_delta,
            "new_balance":     new_available,
            "message":         f"Wallet adjusted by {int_delta:+d} points",
        }

    except UniqueViolationError:
        logger.warning("Duplicate adjustment reference for review %s — skipping", review_id)
        raise HTTPException(status_code=409,
                            detail="Wallet adjustment already recorded for this review update")