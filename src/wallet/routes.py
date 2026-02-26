from fastapi import APIRouter, Depends, Query, Path, Header, HTTPException
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from src.core.security import SECRET_KEY
from src.core.logger import setup_logger

from src.wallet.schemas import (
    WalletBalanceResponse,
    WalletResponse
)
from src.wallet.service import (
    get_wallet_by_employee,
    get_wallet_balance,
    get_points_summary,
    credit_wallet_from_review
)
from src.wallet.dependencies import CurrentUser, get_current_user, require_roles


logger = setup_logger(__name__)

# Main router
router = APIRouter()

# Wallets Router
wallets_router = APIRouter(prefix="/wallets", tags=["Wallets"])

#internal Router
internal_router = APIRouter(prefix="/internal", tags = ["Internal"])

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

@internal_router.post("/credit-from-review")
async def credit_from_review_route(
    review_id: str,
   x_internal_api_key: str = Header(None)
):
    """Credit wallet based on review rating. Triggered automatically after review creation. No admin required."""
    if not  x_internal_api_key or x_internal_api_key!= SECRET_KEY:
        logger.warning("Unauthorized internal credit attempt")
        raise HTTPException(status_code = 403, detail = "Unauthorized service")
    logger.info(
        "Internal credit request received for review_id=%s",
        review_id
    )
    return await credit_wallet_from_review(review_id)
# Include sub-router
router.include_router(wallets_router)
router.include_router(internal_router)