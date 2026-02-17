from fastapi import APIRouter, Depends, Query, Path
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from src.wallet.schemas import (
    TransactionCreate,
    TransactionResponse,
    TransactionListResponse,
    WalletBalanceResponse,
    WalletBalanceResponse,
    WalletResponse,
    TransactionTypeInfo
)
from src.wallet.service import (
    create_transaction,
    get_transactions,
    get_transaction_by_id,
    get_wallet_by_employee,
    get_wallet_balance,
    get_points_summary,
    get_points_summary,
    credit_wallet_from_review,
    get_transaction_types
)
from src.wallet.dependencies import CurrentUser, get_current_user, require_roles

# Main router
router = APIRouter()

# Transactions Router
transactions_router = APIRouter(prefix="/transactions", tags=["Transactions"])

@transactions_router.post("", response_model=TransactionResponse)
async def create_txn(
    data: TransactionCreate,
    current_user: CurrentUser = Depends(require_roles("HR_ADMIN", "SUPER_ADMIN"))
):
    txn = await create_transaction(data, current_user)
    
    return {
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
        "updated_by": txn.updated_by,
    }


@transactions_router.get("/types", response_model=List[TransactionTypeInfo])
async def list_transaction_types(
    current_user: CurrentUser = Depends(get_current_user)
):
    return await get_transaction_types(current_user)

@transactions_router.get("", response_model=TransactionListResponse)
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

@transactions_router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """Get a single transaction by ID with full details"""
    return await get_transaction_by_id(transaction_id, current_user)

# Wallets Router
wallets_router = APIRouter(prefix="/wallets", tags=["Wallets"])

@wallets_router.get("/employees/{employee_id}")
async def get_wallet(
    employee_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return await get_wallet_by_employee(employee_id, current_user)

@wallets_router.get("/{wallet_id}/balance", response_model=WalletBalanceResponse)
async def read_wallet_balance(
    wallet_id: UUID,
    current_user: CurrentUser = Depends(get_current_user)
):
    return await get_wallet_balance(str(wallet_id), current_user)

@wallets_router.get("/{wallet_id}/points-summary")
async def get_points_summary_route(
    wallet_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return await get_points_summary(str(wallet_id), current_user)

@wallets_router.post("/credit-from-review")
async def credit_from_review_route(
    review_id: str,
    current_user: CurrentUser = Depends(require_roles("HR_ADMIN", "SUPER_ADMIN"))
):
    """Credit wallet based on review rating. The created_by is automatically fetched from the review."""
    return await credit_wallet_from_review(review_id, current_user)

# Include sub-routers
router.include_router(transactions_router)
router.include_router(wallets_router)