from fastapi import HTTPException, status
from prisma.errors import UniqueViolationError
from src.prisma.client import db
from datetime import datetime, timezone
from src.wallet.dependencies import CurrentUser
from src.core.logger import setup_logger


logger = setup_logger(__name__)

# -----------------------------
# Utility
# -----------------------------

WNF = "Wallet not found"
AD = "Access Denied"

def is_admin(user: CurrentUser) -> bool:
    return any(role in user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])


def calculate_points_from_rating(rating: int) -> int:
    if rating < 3:
        return 0
    elif rating == 3:
        return 10
    elif rating == 4:
        return 20
    elif rating == 5:
        return 50
    return 0


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
        raise HTTPException(status_code=403, detail="Access denied")

    wallet = await db.wallets.find_unique(
        where={"employee_id": employee_id}
    )

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
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "wallet_id": str(wallet.wallet_id),
        "available_points": wallet.available_points
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
        raise HTTPException(status_code=403, detail="Access denied")

    now = datetime.now(timezone.utc)

    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_of_year = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

    month_txns = await db.transactions.find_many(
        where={
            "wallet_id": wallet_id,
            "transaction_at": {"gte": start_of_month},
        }
    )

    year_txns = await db.transactions.find_many(
        where={
            "wallet_id": wallet_id,
            "transaction_at": {"gte": start_of_year},
        }
    )

    logger.info(
        "Computed summary wallet_id=%s month_txns=%d year_txns=%d",
        wallet_id,
        len(month_txns),
        len(year_txns)
    )
    return {
        "wallet_id": wallet_id,
        "points_this_month": sum(txn.amount for txn in month_txns),
        "points_this_year": sum(txn.amount for txn in year_txns)
    }

async def credit_wallet_from_review(review_id: str):
    review_id = str(review_id)

    # 1. Fetch review
    review = await db.reviews.find_unique(
        where={"review_id": review_id}
    )
    if not review:
        logger.warning(
            "Review not found for review_id=%s",
            review_id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found"
        )

    employee_id = review.receiver_id
    created_by = review.created_by  # Get created_by from the review itself

    # 2. Convert rating -> points
    points = calculate_points_from_rating(review.rating)

    if points == 0:
        return {
            "message": "No points awarded for this rating",
            "credited_points": 0
        }

    # 3. Fetch wallet
    wallet = await db.wallets.find_unique(
        where={"employee_id": employee_id}
    )
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Wallet not found"
        )

    # 4. Fetch transaction type (CREDIT) and status (APPROVED)
    # Seed: run seed_transaction_types.py once to create the CREDIT type
    txn_type = await db.transaction_types.find_unique(
        where={"type_code": "CREDIT"}
    )
    if not txn_type:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CREDIT transaction type missing. Run seed_transaction_types.py once to seed it."
        )

    status_record = await db.status_master.find_first(
        where={"status_code": "APPROVED"}
    )
    if not status_record:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="APPROVED status not found in status_master. Run seed_transaction_types.py"
        )

    # 5. Idempotent reference
    reference = f"REVIEW-{review_id}"

    new_available = wallet.available_points + points
    new_total = wallet.total_earned_points + points

    try:
        async with db.tx() as transaction:

            new_txn = await transaction.transactions.create(
                data={
                    "wallet_id": wallet.wallet_id,
                    "amount": points,
                    "transaction_type_id": txn_type.type_id,
                    "status_id": status_record.status_id,
                    "description": f"Points for {review.rating}-rating review",
                    "reference_number": reference,
                    "created_by": created_by,
                    "updated_by": created_by,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
            )

            result = await transaction.wallets.update_many(
                where={
                    "wallet_id": wallet.wallet_id,
                    "version": wallet.version
                },
                data={
                    "available_points": new_available,
                    "total_earned_points": new_total,
                    "version": wallet.version + 1,
                    "updated_by": created_by,
                }
            )

            if result == 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Wallet updated concurrently"
                )

        return new_txn

    except UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Points already credited for this review"
        )


async def get_transaction_types(current_user: CurrentUser):
    # Only admins should access system configs
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    types = await db.transaction_types.find_many()

    return [
        {
            "type_id": str(t.type_id),
            "code": t.type_code,
            "name": t.type_name,
            "is_credit": t.is_credit
        }
        for t in types
    ]