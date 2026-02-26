from fastapi import APIRouter, Depends, Query
from typing import List
from datetime import datetime

from src.transaction.schemas import (
    TransactionCreate,
    TransactionResponse,
    TransactionListResponse,
    TransactionTypeInfo
)

from src.transaction.service import (
    create_transaction,
    get_transactions,
    get_transaction_by_id,
    get_transaction_types
)

from src.transaction.dependencies import CurrentUser, get_current_user, require_roles

# Main router
router = APIRouter()

# Transactions Router

transaction_router = APIRouter(prefix= "/transactions", tags = ["Transactions"])


@transaction_router.post("", response_model = TransactionResponse)
async def create_tnx(
    data: TransactionCreate,
    current_user: CurrentUser = Depends(require_roles("HR_ADMIN", "SUPER_ADMIN"))
):
    txn = await create_transaction(data, current_user)

    return {
        "transaction_id": txn.transaction_id,
        "wallet_id": txn.wallet_id,
        "amount": txn.amount,
        "status" : {
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
        "updated_by": txn.updated_by,
    }

@transaction_router.get("/types", response_model = List[TransactionTypeInfo])
async def list_transaction_types(
    current_user: CurrentUser = Depends(require_roles("HR_ADMIN", "SUPER_ADMIN"))
):
    return await get_transaction_types(current_user)

@transaction_router.get("", response_model=TransactionListResponse)
async def list_transaction(
    wallet_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    start_date: datetime | None = Query(None, description="Filter transactions after this date"),
    end_date: datetime | None = Query(None, description="Filter transactions before this date"),
    status_code: str | None = Query(None, description="Filter by status code (SUCCESS, FAILED, REFUNDED)"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get wallet transactions with optional filtering.
    
    **Query Parameters:**
    - wallet_id: Wallet ID (required)
    - page: Page number (default: 1)
    - limit: Items per page (default: 10, max: 100)
    - start_date: Filter transactions from this date onwards
    - end_date: Filter transactions up to this date
    - status_code: Filter by status (SUCCESS, FAILED, REFUNDED, etc.)
    """
    return await get_transactions(
        wallet_id=wallet_id,
        page=page,
        limit=limit,
        current_user=current_user,
        start_date=start_date,
        end_date=end_date,
        status_code=status_code
    )

@transaction_router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a single transaction by ID with full details"""
    return await get_transaction_by_id(transaction_id, current_user)


router.include_router(transaction_router)