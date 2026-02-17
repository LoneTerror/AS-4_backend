from fastapi import HTTPException, status
from prisma.errors import UniqueViolationError
from src.prisma.client import db
from datetime import datetime, timezone
from src.wallet.dependencies import CurrentUser


# -----------------------------
# Utility
# -----------------------------

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
# Transaction creation
# -----------------------------

async def create_transaction(data, current_user: CurrentUser):
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create transactions"
        )

    wallet_id = str(data.wallet_id)
    txn_type_id = str(data.transaction_type_id)
    created_by = current_user.id
    amount = data.amount

    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero"
        )

    wallet = await db.wallets.find_unique(
        where={"wallet_id": wallet_id}
    )
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    txn_type = await db.transaction_types.find_unique(
        where={"type_id": txn_type_id}
    )
    if not txn_type:
        raise HTTPException(status_code=404, detail="Transaction type not found")

    # Look up transaction status — DB uses APPROVED for transactions
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
        raise HTTPException(
            status_code=400,
            detail="Insufficient wallet balance"
        )

    new_available = wallet.available_points
    new_redeemed = wallet.redeemed_points
    new_total = wallet.total_earned_points

    if txn_type.is_credit:
        new_available += amount
        new_total += amount
    else:
        new_available -= amount
        new_redeemed += amount

    try:
        async with db.tx() as transaction:

            new_txn = await transaction.transactions.create(
                data={
                    "wallet_id": wallet_id,
                    "amount": amount,
                    "transaction_type_id": txn_type_id,
                    "status_id": status_id,
                    "description": data.description,
                    "reference_number": data.reference_number,
                    "created_by": created_by,
                    "updated_by": created_by,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
            )

            result = await transaction.wallets.update_many(
                where={
                    "wallet_id": wallet_id,
                    "version": wallet.version
                },
                data={
                    "available_points": new_available,
                    "redeemed_points": new_redeemed,
                    "total_earned_points": new_total,
                    "version": wallet.version + 1,
                    "updated_by": created_by,
                }
            )

            if result == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Wallet was updated by another transaction."
                )

        # Fetch full transaction with relations for response schema
        final_txn = await db.transactions.find_unique(
            where={"transaction_id": new_txn.transaction_id},
            include={
                "status_master": True,
                "transaction_types": True
            }
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
    status_code: str | None = None
):
    import traceback
    try:
        wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")

        if not is_admin(current_user) and wallet.employee_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        page = max(page, 1)
        limit = min(max(limit, 1), 100)
        skip = (page - 1) * limit

        where_clause = {"wallet_id": wallet_id}

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
            include={
                "status_master": True,
                "transaction_types": True
            }
        )

        total = await db.transactions.count(where=where_clause)

        formatted = []
        for txn in transactions:
            formatted.append({
                "transaction_id": txn.transaction_id,
                "wallet_id": txn.wallet_id,
                "amount": txn.amount,
                "status": {
                    "status_id": str(txn.status_master.status_id),
                    "code": txn.status_master.status_code,
                    "name": txn.status_master.status_name
                },
                "transaction_type": {
                    "type_id": str(txn.transaction_types.type_id),
                    "code": txn.transaction_types.type_code,
                    "name": txn.transaction_types.type_name,
                    "is_credit": txn.transaction_types.is_credit
                },
                "reference_number": txn.reference_number,
                "description": txn.description,
                "transaction_at": txn.transaction_at,
                "created_at": txn.created_at,
                "updated_at": txn.updated_at,
                "created_by": txn.created_by,
                "updated_by": txn.updated_by
            })

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "transactions": formatted
        }
    except Exception as e:
        print(f"ERROR in get_transactions: {e}")
        with open("error.log", "w") as f:
            f.write(f"ERROR in get_transactions: {e}\n")
            traceback.print_exc(file=f)
        traceback.print_exc()
        raise e


async def get_transaction_by_id(transaction_id: str, current_user: CurrentUser):
    from src.wallet.schemas import StatusInfo, TransactionTypeInfo
    
    txn = await db.transactions.find_unique(
        where={"transaction_id": transaction_id},
        include={
            "status_master": True,
            "transaction_types": True
        }
    )

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if not is_admin(current_user):
        wallet = await db.wallets.find_unique(
            where={"wallet_id": txn.wallet_id}
        )
        if not wallet or wallet.employee_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    # Transform to response format
    return {
        "transaction_id": txn.transaction_id,
        "wallet_id": txn.wallet_id,
        "amount": txn.amount,
        "status": StatusInfo.from_db(txn.status_master),
        "transaction_type": TransactionTypeInfo.from_db(txn.transaction_types),
        "reference_number": txn.reference_number,
        "description": txn.description,
        "transaction_at": txn.transaction_at,
        "created_at": txn.created_at,
        "updated_at": txn.updated_at,
        "created_by": txn.created_by,
        "updated_by": txn.updated_by,
    }


# -----------------------------
# Wallet queries
# -----------------------------

async def get_wallet_by_employee(employee_id: str, current_user: CurrentUser):
    if not is_admin(current_user) and employee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    wallet = await db.wallets.find_unique(
        where={"employee_id": employee_id}
    )

    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    return wallet


async def get_wallet_balance(wallet_id: str, current_user: CurrentUser):
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

    return {
        "wallet_id": wallet_id,
        "points_this_month": sum(txn.amount for txn in month_txns),
        "points_this_year": sum(txn.amount for txn in year_txns)
    }

async def credit_wallet_from_review(review_id: str, current_user: CurrentUser):
    review_id = str(review_id)

    # 1. Fetch review
    review = await db.reviews.find_unique(
        where={"review_id": review_id}
    )
    if not review:
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