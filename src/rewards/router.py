from fastapi import APIRouter, Depends, status, Request, HTTPException
from typing import List, Optional
from prisma import Prisma
from slowapi import Limiter
from slowapi.util import get_remote_address

from . import schemas
from . import service
from . import dependencies
from .database import get_db

router = APIRouter(
    prefix="/v1/rewards",
    tags=["Rewards"]
)

limiter = Limiter(key_func=get_remote_address)

# CATEGORY ENDPOINTS

@router.post("/categories", response_model=schemas.CategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(
    request: Request,  
    body: schemas.CreateCategoryRequest,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.require_roles("ADMIN", "HR_ADMIN"))
):
    """
    Create a new reward category.
    """
    svc = service.RewardService(db)
    return await svc.create_category(body, user_id=current_user.id, req_info=request)


@router.patch("/categories/{category_id}", response_model=schemas.CategoryResponse)
async def update_category(
    category_id: str,
    request: Request, 
    body: schemas.UpdateCategoryRequest,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.require_roles("ADMIN", "HR_ADMIN"))
):
    """
    Update a category.
    """
    svc = service.RewardService(db)
    return await svc.update_category(category_id, body, user_id=current_user.id, req_info=request)


@router.get("/categories", response_model=List[schemas.CategoryResponse])
async def get_categories(
    active_only: bool = True,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.get_current_user)
):
    svc = service.RewardService(db)
    return await svc.get_categories(active_only=active_only)

# CATALOG ENDPOINTS
@router.post("/catalog", response_model=schemas.RewardItemResponse, status_code=status.HTTP_201_CREATED)
async def create_reward_item(
    request: Request, 
    item: schemas.CreateRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.require_roles("ADMIN", "HR_ADMIN"))                          
):
    svc = service.RewardService(db)
    return await svc.create_item(item, user_id=current_user.id, req_info=request)


@router.patch("/catalog/{catalog_id}", response_model=schemas.RewardItemResponse)
async def update_reward_item(
    catalog_id: str,
    request: Request, 
    body: schemas.UpdateRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.require_roles("ADMIN", "HR_ADMIN"))
):
    svc = service.RewardService(db)
    return await svc.update_item(catalog_id, body, user_id=current_user.id, req_info=request)


@router.get("/catalog", response_model=schemas.PaginatedCatalogResponse)
async def view_catalog(
    active_only: bool = True,
    page: int = 1,    
    size: int = 20,    
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.get_current_user)
):
    """
    View the catalog with pagination and nested category details.
    """
    svc = service.RewardService(db)
    return await svc.get_catalog(active_only=active_only, page=page, size=size)

@router.patch("/catalog/{catalog_id}/stock", response_model=schemas.RewardItemResponse)
async def restock_item(
    catalog_id: str,
    body: schemas.AddStockRequest,
    request: Request,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.get_current_user)
):
    """Adds stock to an existing reward item."""
    svc = service.RewardService(db)
    return await svc.add_stock(catalog_id, body, current_user.id, request)

# REDEMPTION & HISTORY ENDPOINTS

@router.post("/redeem", response_model=schemas.RedemptionResponse, status_code=status.HTTP_201_CREATED) 
@limiter.limit("5/minute")
async def redeem_reward(
    request: Request, 
    body: schemas.GrantRewardRequest,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.get_current_user)
):
    svc = service.RewardService(db)
    return await svc.grant_reward(
        request=body, 
        granted_by_user_id=current_user.id
    )


# REWARD HISTORY ENDPOINTS
@router.get("/history/me", response_model=schemas.PaginatedHistoryResponse)
async def get_my_history(
    page: int = 1,
    size: int = 10,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.get_current_user)
):
    """
    View ONLY my own reward history.
    """
    svc = service.RewardService(db)

    my_wallet_id = await svc.get_wallet_id_for_user(current_user.id)
    
    if not my_wallet_id:
        return {"data": [], "total_items": 0, "page": page, "size": size}

    return await svc.get_history(wallet_id=my_wallet_id, page=page, size=size)


@router.get("/history", response_model=schemas.PaginatedHistoryResponse)
async def get_all_history(
    wallet_id: Optional[str] = None, 
    page: int = 1,
    size: int = 10,
    db: Prisma = Depends(get_db),
    current_user: dependencies.CurrentUser = Depends(dependencies.require_roles("ADMIN", "HR_ADMIN"))
):
    """
    Admin View: View history for ALL users, or filter by a specific wallet.
    """
    svc = service.RewardService(db)
    return await svc.get_history(wallet_id=wallet_id, page=page, size=size)