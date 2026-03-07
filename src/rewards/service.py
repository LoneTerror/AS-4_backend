"""src/rewards/service.py — with Redis caching."""
import json
import uuid
from fastapi import HTTPException, status, Request
from prisma import Prisma, Json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from . import schemas
from src.core.logger import logger
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType
from src.common.cache import cache_get, cache_set, invalidate_pattern

# ─────────────────────────────────────────────────────────────────────────────
# TTLs (seconds)
# ─────────────────────────────────────────────────────────────────────────────
TTL_CATALOG    = 600   # 10 min — almost never changes
TTL_CATEGORIES = 600   # 10 min — rarely changes
TTL_HISTORY    = 60    # 1 min  — per-wallet, invalidated on redeem

# ─────────────────────────────────────────────────────────────────────────────
# Cache-key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _key_catalog(active_only: bool, page: int, size: int) -> str:
    return f"rewards:catalog:{active_only}:{page}:{size}"

def _key_categories(active_only: bool) -> str:
    return f"rewards:categories:{active_only}"

def _key_history(wallet_id: Optional[str], page: int, size: int) -> str:
    wid = wallet_id or "all"
    return f"rewards:history:{wid}:{page}:{size}"


# ─────────────────────────────────────────────────────────────────────────────
# Public invalidation helpers  (called after writes)
# ─────────────────────────────────────────────────────────────────────────────

async def invalidate_catalog() -> None:
    await invalidate_pattern("rewards:catalog:*")

async def invalidate_categories() -> None:
    await invalidate_pattern("rewards:categories:*")

async def invalidate_history(wallet_id: Optional[str] = None) -> None:
    """Bust a specific wallet's history pages, plus the global 'all' pages."""
    await invalidate_pattern("rewards:history:all:*")
    if wallet_id:
        await invalidate_pattern(f"rewards:history:{wallet_id}:*")


class RewardService:
    def __init__(self, db: Prisma):
        self.db = db
        try:
            from src.notifications.redis_client import get_redis
            r = get_redis()
        except RuntimeError:
            r = None
        self._notif = NotificationService(db, redis=r)

    # ─────────────────────────────────────────────────────────────────────────
    # Audit log helper
    # ─────────────────────────────────────────────────────────────────────────
    async def _log_change(
        self,
        table_name: str,
        record_id: str,
        operation: str,
        user_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None
    ):
        try:
            await self.db.audit_log.create(
                data={
                    "table_name": table_name,
                    "record_id": record_id,
                    "operation_type": operation,
                    "performed_by": user_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    "old_values": Json(old_values) if old_values else Json({}),
                    "new_values": Json(new_values) if new_values else Json({})
                }
            )
        except Exception as e:
            logger.error(f"FAILED TO AUDIT LOG: {e}", exc_info=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────
    async def _get_sys_id(self, table, code_field, code_value):
        record = await getattr(self.db, table).find_unique(where={code_field: code_value})
        if not record:
            raise HTTPException(status_code=500,
                detail=f"System Configuration Error: {code_value} not found in {table}")
        if table == "transaction_types": return record.type_id
        if table == "status_master":     return record.status_id
        return None

    def _get_stock_status(self, stock: int) -> str:
        if stock <= 0:  return "Out of Stock"
        if stock < 10:  return "Limited Stock"
        return "In Stock"

    # ─────────────────────────────────────────────────────────────────────────
    # Category management
    # ─────────────────────────────────────────────────────────────────────────
    async def create_category(self, request: schemas.CreateCategoryRequest, user_id: str, req_info: Request):
        existing = await self.db.reward_categories.find_unique(
            where={"category_code": request.category_code}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Category code already exists")

        new_category = await self.db.reward_categories.create(
            data={
                "category_name": request.category_name,
                "category_code": request.category_code,
                "description": request.description,
                "created_by": user_id,
                "updated_by": user_id,
                "updated_at": datetime.now(timezone.utc)
            }
        )

        await self._log_change(
            table_name="reward_categories", record_id=new_category.category_id,
            operation="INSERT", user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            new_values=new_category.model_dump()
        )

        await invalidate_categories()
        return new_category

    async def get_categories(self, is_active: Optional[bool] = None):
        """
        Returns categories, using Redis cache when available.
        is_active=True  → only is_active=True rows
        is_active=False → only is_active=False rows
        is_active=None  → all rows (admin view)
        """
        # Generate a dynamic cache key based on the filter
        key = f"categories_list_active:{is_active}"
        
        cached = await cache_get(key)
        if cached is not None:
            logger.debug("cache HIT %s", key)
            return cached  # plain list of dicts — Pydantic validation happens in router

        # --- FIXED LOGIC FOR ERR-442 ---
        where_clause = {}
        if is_active is not None:
            # This safely handles both True and False strict boolean checks
            where_clause = {"is_active": is_active}
        # -------------------------------

        result = await self.db.reward_categories.find_many(where=where_clause)
        serialised = [r.model_dump() for r in result]
        
        await cache_set(key, serialised, ttl=TTL_CATEGORIES)
        return result

    async def update_category(self, category_id: str, request: schemas.UpdateCategoryRequest,
                               user_id: str, req_info: Request):
        existing = await self.db.reward_categories.find_unique(where={"category_id": category_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")

        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        has_changes = any(
            getattr(existing, k, None) != v
            for k, v in update_data.items()
        )
        if not has_changes:
            raise HTTPException(
                status_code=400,
                detail="The provided values are identical to the current data. No update required."
            )

        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_category = await self.db.reward_categories.update(
            where={"category_id": category_id}, data=update_data
        )

        await self._log_change(
            table_name="reward_categories", record_id=category_id,
            operation="UPDATE", user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            old_values=existing.model_dump(), new_values=updated_category.model_dump()
        )

        await invalidate_categories()
        return updated_category

    # ─────────────────────────────────────────────────────────────────────────
    # Catalog management
    # ─────────────────────────────────────────────────────────────────────────
    async def create_item(self, item: schemas.CreateRewardRequest, user_id: str, req_info: Request):
        category = await self.db.reward_categories.find_unique(
            where={"category_id": str(item.category_id)}
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        if not category.is_active:
            logger.warning(f"Failed to create reward: Category {item.category_id} is inactive.")
            raise HTTPException(
                status_code=400,
                detail="Cannot create a reward item under an inactive category. Please activate the category first."
            )

        existing = await self.db.reward_catalog.find_unique(where={"reward_code": item.reward_code})
        if existing:
            raise HTTPException(status_code=400, detail="Reward code already exists")

        new_item = await self.db.reward_catalog.create(
            data={
                "reward_name": item.reward_name,
                "reward_code": item.reward_code,
                "description": item.description,
                "category_id": str(item.category_id),
                "default_points": item.default_points,
                "min_points": item.min_points,
                "max_points": item.max_points,
                "available_stock": item.available_stock if item.available_stock is not None else 0,
                "created_by": user_id,
                "updated_by": user_id,
                "updated_at": datetime.now(timezone.utc)
            },
            include={"reward_categories": True}
        )

        await self._log_change(
            table_name="reward_catalog", record_id=new_item.catalog_id,
            operation="INSERT", user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            new_values=new_item.model_dump()
        )

        await invalidate_catalog()

        cat_data = None
        if new_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=new_item.reward_categories.category_id,
                category_name=new_item.reward_categories.category_name,
                category_code=new_item.reward_categories.category_code
            )

        return schemas.RewardItemResponse(
            catalog_id=new_item.catalog_id,
            reward_name=new_item.reward_name,
            reward_code=new_item.reward_code,
            description=new_item.description,
            default_points=new_item.default_points,
            min_points=new_item.min_points,
            max_points=new_item.max_points,
            is_active=new_item.is_active,
            created_at=new_item.created_at,
            category=cat_data,
            stock_status=self._get_stock_status(new_item.available_stock),
            available_stock=new_item.available_stock
        )

    async def get_catalog(self, active_only: bool = True, page: int = 1, size: int = 20):
        key = _key_catalog(active_only, page, size)
        cached = await cache_get(key)
        if cached is not None:
            logger.debug("cache HIT %s", key)
            return cached

        skip = (page - 1) * size
        where_clause = {"is_active": True} if active_only else {}
        total_items = await self.db.reward_catalog.count(where=where_clause)

        items = await self.db.reward_catalog.find_many(
            where=where_clause,
            skip=skip,
            take=size,
            order={"created_at": "desc"},
            include={"reward_categories": True}
        )

        mapped_data = []
        for item in items:
            cat_data = None
            if item.reward_categories:
                cat_data = schemas.MinimalCategoryInfo(
                    category_id=item.reward_categories.category_id,
                    category_name=item.reward_categories.category_name,
                    category_code=item.reward_categories.category_code
                )

            mapped_data.append(schemas.RewardItemResponse(
                catalog_id=item.catalog_id,
                reward_name=item.reward_name,
                reward_code=item.reward_code,
                description=item.description,
                default_points=item.default_points,
                min_points=item.min_points,
                max_points=item.max_points,
                is_active=item.is_active,
                created_at=item.created_at,
                category=cat_data,
                stock_status=self._get_stock_status(item.available_stock),
                available_stock=item.available_stock
            ))

        total_pages = (total_items + size - 1) // size
        result = {
            "data": [r.model_dump() for r in mapped_data],
            "pagination": {
                "current_page": page,
                "per_page": size,
                "total": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1
            }
        }

        await cache_set(key, result, ttl=TTL_CATALOG)
        return {**result, "data": mapped_data}

    async def add_stock(self, catalog_id: str, request: schemas.AddStockRequest,
                        user_id: str, req_info: Request):
        existing_item = await self.db.reward_catalog.find_unique(where={"catalog_id": catalog_id})
        if not existing_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        updated_item = await self.db.reward_catalog.update(
            where={"catalog_id": catalog_id},
            data={
                "available_stock": {"increment": request.amount},
                "updated_by": user_id,
                "updated_at": datetime.now(timezone.utc)
            },
            include={"reward_categories": True}
        )

        await self._log_change(
            table_name="reward_catalog", record_id=catalog_id,
            operation="RESTOCK", user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            old_values={"available_stock": existing_item.available_stock},
            new_values={"available_stock": updated_item.available_stock, "added": request.amount}
        )

        await invalidate_catalog()

        cat_data = None
        if updated_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=updated_item.reward_categories.category_id,
                category_name=updated_item.reward_categories.category_name,
                category_code=updated_item.reward_categories.category_code
            )

        return schemas.RewardItemResponse(
            catalog_id=updated_item.catalog_id,
            reward_name=updated_item.reward_name,
            reward_code=updated_item.reward_code,
            description=updated_item.description,
            default_points=updated_item.default_points,
            min_points=updated_item.min_points,
            max_points=updated_item.max_points,
            is_active=updated_item.is_active,
            created_at=updated_item.created_at,
            category=cat_data,
            stock_status=self._get_stock_status(updated_item.available_stock),
            available_stock=updated_item.available_stock
        )

    async def update_item(self, catalog_id: str, request: schemas.UpdateRewardRequest,
                          user_id: str, req_info: Request):
        existing_item = await self.db.reward_catalog.find_unique(where={"catalog_id": catalog_id})
        if not existing_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        # Resolve final min / default / max (provided value or fall back to existing)
        new_min     = request.min_points     if request.min_points     is not None else existing_item.min_points
        new_max     = request.max_points     if request.max_points     is not None else existing_item.max_points
        new_default = request.default_points if request.default_points is not None else existing_item.default_points

        if new_min > new_max:
            raise HTTPException(
                status_code=400,
                detail=f"Min points ({new_min}) cannot be greater than Max points ({new_max})"
            )

        if not (new_min <= new_default <= new_max):
            raise HTTPException(
                status_code=400,
                detail=f"Default points ({new_default}) must be between Min points ({new_min}) and Max points ({new_max})"
            )

        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        # Validate category change if requested
        new_category = None
        if "category_id" in update_data:
            new_cat_id = str(update_data["category_id"])
            new_category = await self.db.reward_categories.find_unique(
                where={"category_id": new_cat_id}
            )
            if not new_category:
                raise HTTPException(status_code=404, detail="The specified target category was not found.")
            if not new_category.is_active:
                logger.warning(f"Failed to move reward: Target category {new_cat_id} is inactive.")
                raise HTTPException(
                    status_code=400,
                    detail="Cannot move a reward item to an inactive category. Please activate the target category first."
                )
            update_data["category_id"] = new_cat_id

        # Prevent reactivating a reward whose parent category is inactive
        if update_data.get("is_active") is True:
            check_cat_id = update_data.get("category_id", existing_item.category_id)
            cat_to_check = new_category if new_category else await self.db.reward_categories.find_unique(
                where={"category_id": check_cat_id}
            )
            if cat_to_check and not cat_to_check.is_active:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot reactivate this reward because its parent category is currently inactive."
                )

        # Guard: reject no-op updates
        has_changes = any(
            getattr(existing_item, k, None) != v
            for k, v in update_data.items()
        )
        if not has_changes:
            raise HTTPException(
                status_code=400,
                detail="The provided values are identical to the current data. No update required."
            )

        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_item = await self.db.reward_catalog.update(
            where={"catalog_id": catalog_id},
            data=update_data,
            include={"reward_categories": True}
        )

        await self._log_change(
            table_name="reward_catalog", record_id=catalog_id,
            operation="UPDATE", user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            old_values=existing_item.model_dump(), new_values=updated_item.model_dump()
        )

        await invalidate_catalog()

        cat_data = None
        if updated_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=updated_item.reward_categories.category_id,
                category_name=updated_item.reward_categories.category_name,
                category_code=updated_item.reward_categories.category_code
            )

        return schemas.RewardItemResponse(
            catalog_id=updated_item.catalog_id,
            reward_name=updated_item.reward_name,
            reward_code=updated_item.reward_code,
            description=updated_item.description,
            default_points=updated_item.default_points,
            min_points=updated_item.min_points,
            max_points=updated_item.max_points,
            is_active=updated_item.is_active,
            created_at=updated_item.created_at,
            category=cat_data,
            stock_status=self._get_stock_status(updated_item.available_stock),
            available_stock=updated_item.available_stock
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Redemption
    # ─────────────────────────────────────────────────────────────────────────
    async def grant_reward(self, request: schemas.GrantRewardRequest, granted_by_user_id: str):
        logger.info(f"Initiating grant_reward. Catalog ID: {request.catalog_id}, Wallet ID: {request.wallet_id}")

        reward_item = await self.db.reward_catalog.find_unique(
            where={"catalog_id": str(request.catalog_id)}
        )
        if not reward_item or not reward_item.is_active:
            raise HTTPException(status_code=400, detail="Reward is invalid or inactive")

        if reward_item.available_stock <= 0:
            raise HTTPException(status_code=400, detail="Out of stock! This reward is no longer available.")

        if request.points < reward_item.min_points or request.points > reward_item.max_points:
            raise HTTPException(status_code=400, detail="Points are outside the allowed range")

        wallet = await self.db.wallets.find_unique(where={"wallet_id": str(request.wallet_id)})
        if not wallet:
            raise HTTPException(status_code=404, detail="Wallet not found")

        if wallet.available_points < request.points:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")

        type_id   = await self._get_sys_id("transaction_types", "type_code", "REWARD_REDEMPTION")
        status_id = await self._get_sys_id("status_master",     "status_code", "APPROVED")

        ref_number = f"TXN-{int(datetime.now().timestamp())}-{str(uuid.uuid4())[:8]}"

        try:
            async with self.db.tx() as transaction:
                await transaction.wallets.update(
                    where={"wallet_id": str(request.wallet_id)},
                    data={
                        "available_points": {"decrement": request.points},
                        "redeemed_points":  {"increment": request.points},
                        "updated_by": granted_by_user_id,
                        "updated_at": datetime.now(timezone.utc)
                    }
                )

                updated_catalog = await transaction.reward_catalog.update(
                    where={
                        "catalog_id": str(request.catalog_id),
                        "available_stock": {"gt": 0}
                    },
                    data={
                        "available_stock": {"decrement": 1},
                        "updated_at": datetime.now(timezone.utc),
                        "updated_by": granted_by_user_id
                    }
                )

                if not updated_catalog:
                    raise HTTPException(status_code=400,
                        detail="Out of stock! This reward was just claimed by someone else.")

                await transaction.transactions.create(
                    data={
                        "wallet_id": str(request.wallet_id),
                        "amount": request.points,
                        "transaction_type_id": type_id,
                        "status_id": status_id,
                        "description": f"Redeemed: {reward_item.reward_name}",
                        "reference_number": ref_number,
                        "transaction_at": datetime.now(timezone.utc),
                        "created_by": granted_by_user_id,
                        "updated_by": granted_by_user_id,
                        "updated_at": datetime.now(timezone.utc)
                    }
                )

                history_record = await transaction.reward_history.create(
                    data={
                        "wallet_id": str(request.wallet_id),
                        "catalog_id": str(request.catalog_id),
                        "points": request.points,
                        "granted_by": granted_by_user_id,
                        "comment": request.comment,
                        "created_by": granted_by_user_id,
                        "updated_by": granted_by_user_id,
                        "updated_at": datetime.now(timezone.utc)
                    }
                )

            # Post-commit: invalidate caches & notify
            await invalidate_catalog()
            await invalidate_history(str(request.wallet_id))
            from src.analytics.service import invalidate_leaderboard
            await invalidate_leaderboard()

            try:
                new_balance = wallet.available_points - request.points
                await self._notif.create_notification(
                    employee_id=wallet.employee_id,
                    title=f"You redeemed \"{reward_item.reward_name}\" 🎁",
                    message=(
                        f"{request.points} points were used to redeem "
                        f"\"{reward_item.reward_name}\". "
                        f"Your remaining balance is {new_balance} points."
                        + (f" Note: {request.comment}" if request.comment else "")
                    ),
                    type=NotificationType.REWARD,
                )
            except Exception:
                logger.exception(
                    "Redemption notification failed for history %s — redemption completed successfully",
                    history_record.history_id,
                )

            logger.info(f"Transaction {ref_number} completed for wallet {request.wallet_id}")
            return {
                "history_id":      history_record.history_id,
                "points":          history_record.points,
                "granted_at":      history_record.granted_at,
                "status":          "COMPLETED",
                "new_stock_level": updated_catalog.available_stock
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Atomic transaction failed for {ref_number}: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")

    # ─────────────────────────────────────────────────────────────────────────
    # History
    # ─────────────────────────────────────────────────────────────────────────
    async def get_history(self, wallet_id: Optional[str] = None, page: int = 1, size: int = 10):
        key = _key_history(wallet_id, page, size)
        cached = await cache_get(key)
        if cached is not None:
            logger.debug("cache HIT %s", key)
            return cached

        skip_count = (page - 1) * size
        where_clause = {}
        if wallet_id:
            where_clause["wallet_id"] = wallet_id

        history = await self.db.reward_history.find_many(
            where=where_clause,
            skip=skip_count,
            take=size,
            order={"granted_at": "desc"},
            include={
                "reward_catalog": True,
                "employees_reward_history_granted_byToemployees": True
            }
        )

        total_items = await self.db.reward_history.count(where=where_clause)

        result = {
            "data":        [h.model_dump() for h in history],
            "total_items": total_items,
            "page":        page,
            "size":        size
        }

        await cache_set(key, result, ttl=TTL_HISTORY)
        return {**result, "data": history}

    async def get_wallet_id_for_user(self, user_id: str) -> Optional[str]:
        wallet = await self.db.wallets.find_first(where={"employee_id": user_id})
        return wallet.wallet_id if wallet else None