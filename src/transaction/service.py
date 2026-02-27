from fastapi import FastAPI, HTTPException, status
from prisma.errors import UniqueViolationError
from src.prisma.client import db
from datetime import datetime, timezone
from src.transaction.dependencies import CurrentUser
from src.core.logger import setup_logger
from src.transaction.schemas import StatusInfo, TransactionTypeInfo

logger = setup_logger(__name__)

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

    wallet_id = str(data.wallet_id)
    txn_type_id = str(data.transaction_type_id)
    created_by = current_user.id
    amount = data.amount

    logger.info(
        "Transaction creation requested wallet_id=%s amount=%s by user_id=%s",
        wallet_id,
        amount,
        current_user.id
    )

    if not is_admin(current_user):
        logger.warning(
            "Unauthorized transaction creation attempt by user_id=%s",
            current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to create transactions"
        )

    if amount <= 0:
        logger.warning(
            "Invalid transaction amount=%s by user_id=%s",
            amount,
            current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Amount must be greater than zero"
        )

    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        logger.warning("Wallet not found wallet_id=%s", wallet_id)
        raise HTTPException(status_code=404, detail="Wallet not found")

    txn_type = await db.transaction_types.find_unique(where={"type_id": txn_type_id})
    if not txn_type:
        logger.warning("Transaction type not found type_id=%s", txn_type_id)
        raise HTTPException(status_code=404, detail="Transaction type not found")
    
    all_statuses = await db.status_master.find_many()
    logger.info("All statuses: %s", all_statuses)

    success_status = await db.status_master.find_unique(where={"status_code": "SUCCESS"})
    if not success_status:
        logger.error("Transaction configuration missing: SUCCESS status not found")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transaction configuration missing"
        )

    if not txn_type.is_credit and wallet.available_points < amount:
        logger.warning(
            "Insufficient balance wallet_id=%s amount=%s available=%s",
            wallet_id,
            amount,
            wallet.available_points
        )
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

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
                    "status_id": success_status.status_id,
                    "description": data.description,
                    "reference_number": data.reference_number,
                    "created_by": created_by,
                    "updated_by": created_by,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
            )

            result = await transaction.wallets.update_many(
                where={"wallet_id": wallet_id, "version": wallet.version},
                data={
                    "available_points": new_available,
                    "redeemed_points": new_redeemed,
                    "total_earned_points": new_total,
                    "version": wallet.version + 1,
                    "updated_by": created_by,
                }
            )

            if result == 0:
                logger.error("Concurrent wallet update detected wallet_id=%s", wallet_id)
                raise HTTPException(status_code=409, detail="Wallet updated concurrently")

        logger.info(
            "Transaction created successfully txn_id=%s wallet_id=%s amount=%s",
            new_txn.transaction_id,
            wallet_id,
            amount
        )

        final_txn = await db.transactions.find_unique(
            where={"transaction_id": new_txn.transaction_id},
            include = {
                "status_master": True,
                "transaction_types": True
            }
        )

        if not final_txn:
            logger.error("Transaction not found txn_id=%s", new_txn.transaction_id)
            raise HTTPException(status_code=500, detail = "Transaction fetch failed")

        return final_txn


    except UniqueViolationError:
        logger.warning(
            "Duplicate transaction reference=%s",
            data.reference_number
        )
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

    logger.info(
        "Transaction list requested wallet_id=%s by user_id=%s",
        wallet_id,
        current_user.id
    )

    try:
        wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
        if not wallet:
            logger.warning("Wallet not found wallet_id=%s", wallet_id)
            raise HTTPException(status_code=404, detail="Wallet not found")

        # Access control
        if not is_admin(current_user) and wallet.employee_id != current_user.id:
            logger.warning(
                "Unauthorized transaction list access wallet_id=%s by user_id=%s",
                wallet_id,
                current_user.id
            )
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

        formatted = [
            {
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
            }
            for txn in transactions
        ]

        logger.info(
            "Transaction list fetched wallet_id=%s page=%s limit=%s total=%s",
            wallet_id,
            page,
            limit,
            total
        )

        return {
            "page": page,
            "limit": limit,
            "total": total,
            "transactions": formatted
        }

    except Exception:
        logger.exception(
            "Error fetching transactions wallet_id=%s page=%s limit=%s",
            wallet_id,
            page,
            limit
        )
        raise

async def get_transaction_by_id(transaction_id: str, current_user: CurrentUser):
    logger.info(
        "Transaction fetch requested txn_id=%s by user_id=%s",
        transaction_id,
        current_user.id
    )

    txn = await db.transactions.find_unique(
        where={"transaction_id": transaction_id},
        include={
            "status_master": True,
            "transaction_types": True
        }
    )

    if not txn:
        logger.warning("Transaction not found txn_id=%s", transaction_id)
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Access control
    if not is_admin(current_user):
        wallet = await db.wallets.find_unique(
            where={"wallet_id": txn.wallet_id}
        )

        if not wallet or wallet.employee_id != current_user.id:
            logger.warning(
                "Unauthorized transaction access txn_id=%s by user_id=%s",
                transaction_id,
                current_user.id
            )
            raise HTTPException(status_code=403, detail="Access denied")

    logger.info("Transaction fetch successful txn_id=%s", transaction_id)

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

async def get_transaction_types(current_user: CurrentUser):

    logger.info(
        "Transaction types fetch requested by user_id=%s",
        current_user.id
    )

    if not is_admin(current_user):
        logger.warning(
            "Unauthorized transaction types access attempt by user_id=%s",
            current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )

    try:
        types = await db.transaction_types.find_many()

        logger.info(
            "Transaction types fetched successfully by user_id=%s count=%s",
            current_user.id,
            len(types)
        )

        return [
            {
                "type_id": str(t.type_id),
                "code": t.type_code,
                "name": t.type_name,
                "is_credit": t.is_credit
            }
            for t in types
        ]

    except Exception:
        logger.exception(
            "Error fetching transaction types by user_id=%s",
            current_user.id
        )
        raise