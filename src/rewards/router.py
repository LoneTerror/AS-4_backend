# src/rewards/router.py

from fastapi import APIRouter, Depends, Request, status
from typing import List, Optional
from prisma import Prisma
from src.prisma.client import db

from . import schemas, service
from src.common.dependencies import check_route_permission, CurrentUser
from src.core.logger import logger


async def get_db() -> Prisma:
    return db


COMMON_ERRORS = {
    401: {"model": schemas.ErrorResponse, "description": "Bearer token missing or expired"},
    403: {"model": schemas.ErrorResponse, "description": "Insufficient permissions"},
    500: {"model": schemas.ErrorResponse, "description": "Internal server configuration error"},
}

router = APIRouter(
    prefix="/v1/rewards",
    tags=["Rewards"],
    responses=COMMON_ERRORS,
)


# --- CATEGORY ENDPOINTS ---

@router.post("/categories", response_model=schemas.CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    request: Request,
    body: schemas.CreateCategoryRequest,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create a new reward category."""
    logger.info(f"User {current_user.id} requested to create category: {body.category_name}")
    svc = service.RewardService(db)
    return await svc.create_category(body, user_id=current_user.id, req_info=request)


@router.patch("/categories/{category_id}", response_model=schemas.CategoryResponse)
async def update_category(
    category_id: str,
    request: Request,
    body: schemas.UpdateCategoryRequest,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Update a category."""
    logger.info(f"User {current_user.id} updating category: {category_id}")
    svc = service.RewardService(db)
    return await svc.update_category(category_id, body, user_id=current_user.id, req_info=request)


@router.get("/categories", response_model=List[schemas.CategoryResponse])
async def get_categories(
    active_only: bool = True,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    logger.debug(f"User {current_user.id} fetching categories. Active only: {active_only}")
    svc = service.RewardService(db)
    return await svc.get_categories(active_only=active_only)


# --- CATALOG ENDPOINTS ---

@router.post("/catalog", response_model=schemas.RewardItemResponse, status_code=status.HTTP_201_CREATED)
async def create_reward_item(
    request: Request,
    item: schemas.CreateRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    logger.info(f"Admin {current_user.id} creating reward item: {item.reward_code}")
    svc = service.RewardService(db)
    return await svc.create_item(item, user_id=current_user.id, req_info=request)


@router.patch("/catalog/{catalog_id}", response_model=schemas.RewardItemResponse)
async def update_reward_item(
    catalog_id: str,
    request: Request,
    body: schemas.UpdateRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    logger.info(f"Admin {current_user.id} updating catalog item: {catalog_id}")
    svc = service.RewardService(db)
    return await svc.update_item(catalog_id, body, user_id=current_user.id, req_info=request)


@router.get("/catalog", response_model=schemas.PaginatedCatalogResponse)
async def view_catalog(
    active_only: bool = True,
    page: int = 1,
    size: int = 20,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """View the catalog with pagination and nested category details."""
    logger.debug(f"User {current_user.id} viewing catalog page {page}")
    svc = service.RewardService(db)
    return await svc.get_catalog(active_only=active_only, page=page, size=size)


@router.patch("/catalog/{catalog_id}/stock", response_model=schemas.RewardItemResponse)
async def restock_item(
    catalog_id: str,
    body: schemas.AddStockRequest,
    request: Request,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Adds stock to an existing reward item."""
    logger.info(f"User {current_user.id} restocking item {catalog_id} with {body.amount} units")
    svc = service.RewardService(db)
    return await svc.add_stock(catalog_id, body, current_user.id, request)


# --- REDEMPTION ENDPOINTS ---

@router.post("/redeem", response_model=schemas.RedemptionResponse, status_code=status.HTTP_201_CREATED)
async def redeem_reward(
    request: Request,
    body: schemas.GrantRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    logger.info(f"User {current_user.id} attempting to redeem catalog item {body.catalog_id}")
    svc = service.RewardService(db)
    return await svc.grant_reward(request=body, granted_by_user_id=current_user.id)


# --- REWARD HISTORY ENDPOINTS ---

@router.get("/history/me", response_model=schemas.PaginatedHistoryResponse)
async def get_my_history(
    page: int = 1,
    size: int = 10,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """View ONLY my own reward history."""
    logger.debug(f"User {current_user.id} fetching their personal reward history")
    svc = service.RewardService(db)

    my_wallet_id = await svc.get_wallet_id_for_user(current_user.id)

    if not my_wallet_id:
        logger.warning(f"Failed to fetch history: No wallet found for user {current_user.id}")
        return {"data": [], "total_items": 0, "page": page, "size": size}

    return await svc.get_history(wallet_id=my_wallet_id, page=page, size=size)


@router.get("/history", response_model=schemas.PaginatedHistoryResponse)
async def get_all_history(
    wallet_id: Optional[str] = None,
    page: int = 1,
    size: int = 10,
    db: Prisma = Depends(get_db),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Admin View: View history for ALL users, or filter by a specific wallet."""
    logger.info(f"Admin {current_user.id} fetching global reward history. Filtered by wallet: {wallet_id}")
    svc = service.RewardService(db)
    return await svc.get_history(wallet_id=wallet_id, page=page, size=size)