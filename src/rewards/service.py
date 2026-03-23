# src/rewards/service.py
import uuid
from fastapi import HTTPException, status, Request
from prisma import Prisma
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from . import schemas
from src.core.logger import logger
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType
from src.common import internal_client
from src.common.audit import audit_ctx, audit
from src.common.cache import (
    cache_get, cache_set, cache_delete, invalidate_pattern,
    TTL_VOLATILE,  L1_VOLATILE,
    TTL_MEDIUM,    L1_MEDIUM,
    TTL_PERMANENT, L1_PERMANENT,
)


def _key_catalog(active_only: bool, page: int, size: int) -> str:
    return f"rewards:catalog:{int(active_only)}:{page}:{size}"

def _key_categories(is_active: Optional[bool]) -> str:
    flag = "none" if is_active is None else str(int(is_active))
    return f"rewards:categories:{flag}"

def _key_history(wallet_id: Optional[str], page: int, size: int) -> str:
    wid = wallet_id or "all"
    return f"rewards:history:{wid}:{page}:{size}"

def _key_wallet_id(employee_id: str) -> str:
    return f"rewards:wallet_id:{employee_id}"


async def invalidate_catalog() -> None:
    await invalidate_pattern("rewards:catalog:*")

async def invalidate_categories() -> None:
    await invalidate_pattern("rewards:categories:*")

async def invalidate_history(wallet_id: Optional[str] = None) -> None:
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

    def _get_stock_status(self, stock: int) -> str:
        if stock <= 0:  return "Out of Stock"
        if stock < 10:  return "Limited Stock"
        return "In Stock"

    # ── Category management ───────────────────────────────────────────────────

    async def create_category(
        self, request: schemas.CreateCategoryRequest, user_id: str, req_info: Request
    ):
        existing = await self.db.reward_categories.find_unique(
            where={"category_code": request.category_code}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Category code already exists")

        new_category = None
        async with audit_ctx(
            user_id    = user_id,
            request    = req_info,
            table_name = "reward_categories",
            record_id  = lambda: str(new_category.category_id),
            operation  = "INSERT",
            new_values = lambda: new_category.model_dump(),
        ):
            new_category = await self.db.reward_categories.create(
                data={
                    "category_name": request.category_name,
                    "category_code": request.category_code,
                    "description":   request.description,
                    "created_by":    user_id,
                    "updated_by":    user_id,
                    "updated_at":    datetime.now(timezone.utc),
                }
            )

        await invalidate_categories()
        return new_category

    async def get_categories(self, is_active: Optional[bool] = None):
        key    = _key_categories(is_active)
        cached = await cache_get(key, l1_ttl=L1_MEDIUM)
        if cached is not None:
            return cached
        where_clause = {"is_active": is_active} if is_active is not None else {}
        result       = await self.db.reward_categories.find_many(where=where_clause)
        serialised   = [r.model_dump() for r in result]
        await cache_set(key, serialised, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
        return result

    async def update_category(
        self,
        category_id: str,
        request: schemas.UpdateCategoryRequest,
        user_id: str,
        req_info: Request,
    ):
        existing = await self.db.reward_categories.find_unique(where={"category_id": category_id})
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")

        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        has_changes = any(getattr(existing, k, None) != v for k, v in update_data.items())
        if not has_changes:
            raise HTTPException(status_code=400,
                                detail="The provided values are identical to the current data.")

        old_snapshot = existing.model_dump()
        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_category = None
        async with audit_ctx(
            user_id    = user_id,
            request    = req_info,
            table_name = "reward_categories",
            record_id  = category_id,
            operation  = "UPDATE",
            old_values = old_snapshot,
            new_values = lambda: updated_category.model_dump(),
        ):
            updated_category = await self.db.reward_categories.update(
                where={"category_id": category_id}, data=update_data
            )

        await invalidate_categories()
        return updated_category

    # ── Catalog management ────────────────────────────────────────────────────

    async def create_item(
        self, item: schemas.CreateRewardRequest, user_id: str, req_info: Request
    ):
        category = await self.db.reward_categories.find_unique(
            where={"category_id": str(item.category_id)}
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")
        if not category.is_active:
            raise HTTPException(status_code=400,
                detail="Cannot create a reward item under an inactive category.")

        existing = await self.db.reward_catalog.find_unique(where={"reward_code": item.reward_code})
        if existing:
            raise HTTPException(status_code=400, detail="Reward code already exists")

        new_item = None
        async with audit_ctx(
            user_id    = user_id,
            request    = req_info,
            table_name = "reward_catalog",
            record_id  = lambda: str(new_item.catalog_id),
            operation  = "INSERT",
            new_values = lambda: new_item.model_dump(),
        ):
            new_item = await self.db.reward_catalog.create(
                data={
                    "reward_name":     item.reward_name,
                    "reward_code":     item.reward_code,
                    "description":     item.description,
                    "category_id":     str(item.category_id),
                    "default_points":  item.default_points,
                    "min_points":      item.min_points,
                    "max_points":      item.max_points,
                    "available_stock": item.available_stock if item.available_stock is not None else 0,
                    "created_by":      user_id,
                    "updated_by":      user_id,
                    "updated_at":      datetime.now(timezone.utc),
                },
                include={"reward_categories": True},
            )

        await invalidate_catalog()

        cat_data = None
        if new_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=new_item.reward_categories.category_id,
                category_name=new_item.reward_categories.category_name,
                category_code=new_item.reward_categories.category_code,
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
            available_stock=new_item.available_stock,
        )

    async def get_catalog(self, is_active: Optional[bool] = True, page: int = 1, size: int = 20):
        flag = "all" if is_active is None else str(int(is_active))
        key  = f"rewards:catalog:{flag}:{page}:{size}"
        cached = await cache_get(key, l1_ttl=L1_MEDIUM)
        if cached is not None:
            return cached

        skip         = (page - 1) * size
        where_clause = {"is_active": is_active} if is_active is not None else {}
        total_items  = await self.db.reward_catalog.count(where=where_clause)
        items        = await self.db.reward_catalog.find_many(
            where=where_clause, skip=skip, take=size,
            order={"created_at": "desc"},
            include={"reward_categories": True},
        )

        mapped_data = []
        for item in items:
            cat_data = None
            if item.reward_categories:
                cat_data = schemas.MinimalCategoryInfo(
                    category_id=item.reward_categories.category_id,
                    category_name=item.reward_categories.category_name,
                    category_code=item.reward_categories.category_code,
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
                available_stock=item.available_stock,
            ))

        total_pages = (total_items + size - 1) // size
        result = {
            "data": [r.model_dump() for r in mapped_data],
            "pagination": {
                "current_page": page, "per_page": size, "total": total_items,
                "total_pages": total_pages,
                "has_next": page < total_pages, "has_previous": page > 1,
            },
        }
        await cache_set(key, result, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
        return {**result, "data": mapped_data}

    async def add_stock(
        self,
        catalog_id: str,
        request: schemas.AddStockRequest,
        user_id: str,
        req_info: Request,
    ):
        existing_item = await self.db.reward_catalog.find_unique(where={"catalog_id": catalog_id})
        if not existing_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        old_stock    = existing_item.available_stock
        updated_item = None
        async with audit_ctx(
            user_id    = user_id,
            request    = req_info,
            table_name = "reward_catalog",
            record_id  = catalog_id,
            operation  = "RESTOCK",
            old_values = {"available_stock": old_stock},
            new_values = lambda: {
                "available_stock": updated_item.available_stock,
                "added": request.amount,
            },
        ):
            updated_item = await self.db.reward_catalog.update(
                where={"catalog_id": catalog_id},
                data={
                    "available_stock": {"increment": request.amount},
                    "updated_by":      user_id,
                    "updated_at":      datetime.now(timezone.utc),
                },
                include={"reward_categories": True},
            )

        await invalidate_catalog()

        cat_data = None
        if updated_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=updated_item.reward_categories.category_id,
                category_name=updated_item.reward_categories.category_name,
                category_code=updated_item.reward_categories.category_code,
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
            available_stock=updated_item.available_stock,
        )

    async def update_item(
        self,
        catalog_id: str,
        request: schemas.UpdateRewardRequest,
        user_id: str,
        req_info: Request,
    ):
        existing_item = await self.db.reward_catalog.find_unique(where={"catalog_id": catalog_id})
        if not existing_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        new_min     = request.min_points     if request.min_points     is not None else existing_item.min_points
        new_max     = request.max_points     if request.max_points     is not None else existing_item.max_points
        new_default = request.default_points if request.default_points is not None else existing_item.default_points

        if new_min > new_max:
            raise HTTPException(status_code=400,
                detail=f"Min points ({new_min}) cannot be greater than Max points ({new_max})")
        if not (new_min <= new_default <= new_max):
            raise HTTPException(status_code=400,
                detail=f"Default points ({new_default}) must be between {new_min} and {new_max}")

        update_data = request.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        new_category = None
        if "category_id" in update_data:
            new_cat_id   = str(update_data["category_id"])
            new_category = await self.db.reward_categories.find_unique(
                where={"category_id": new_cat_id}
            )
            if not new_category:
                raise HTTPException(status_code=404, detail="The specified target category was not found.")
            if not new_category.is_active:
                raise HTTPException(status_code=400,
                    detail="Cannot move a reward item to an inactive category.")
            update_data["category_id"] = new_cat_id

        if update_data.get("is_active") is True:
            check_cat_id = update_data.get("category_id", existing_item.category_id)
            cat_to_check = new_category if new_category else \
                await self.db.reward_categories.find_unique(where={"category_id": check_cat_id})
            if cat_to_check and not cat_to_check.is_active:
                raise HTTPException(status_code=400,
                    detail="Cannot reactivate this reward because its parent category is inactive.")

        has_changes = any(getattr(existing_item, k, None) != v for k, v in update_data.items())
        if not has_changes:
            raise HTTPException(status_code=400,
                detail="The provided values are identical to the current data.")

        old_snapshot = existing_item.model_dump()
        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_item = None
        async with audit_ctx(
            user_id    = user_id,
            request    = req_info,
            table_name = "reward_catalog",
            record_id  = catalog_id,
            operation  = "UPDATE",
            old_values = old_snapshot,
            new_values = lambda: updated_item.model_dump(),
        ):
            updated_item = await self.db.reward_catalog.update(
                where={"catalog_id": catalog_id},
                data=update_data,
                include={"reward_categories": True},
            )

        await invalidate_catalog()

        cat_data = None
        if updated_item.reward_categories:
            cat_data = schemas.MinimalCategoryInfo(
                category_id=updated_item.reward_categories.category_id,
                category_name=updated_item.reward_categories.category_name,
                category_code=updated_item.reward_categories.category_code,
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
            available_stock=updated_item.available_stock,
        )

    # ── Redemption ────────────────────────────────────────────────────────────

    async def grant_reward(
        self,
        wallet_id: str,
        request: schemas.RedeemRewardRequest,
        granted_by_user_id: str,
        req_info: Optional[Request] = None,   # ← ADDED: HTTP request for IP/audit
    ):
        logger.info("Initiating grant_reward | catalog=%s wallet=%s",
                    request.catalog_id, wallet_id)

        reward_item = await self.db.reward_catalog.find_unique(
            where={"catalog_id": str(request.catalog_id)}
        )
        if not reward_item or not reward_item.is_active:
            raise HTTPException(status_code=400, detail="Reward is invalid or inactive")
        if reward_item.available_stock <= 0:
            raise HTTPException(status_code=400, detail="Out of stock!")
        if request.points < reward_item.min_points or request.points > reward_item.max_points:
            raise HTTPException(status_code=400, detail="Points are outside the allowed range")

        try:
            wallet_data = await internal_client.get_wallet_by_id(str(wallet_id))
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(status_code=404, detail="Wallet not found")
            raise

        available_points = wallet_data.get("available_points", 0)
        if available_points < request.points:
            raise HTTPException(status_code=400, detail="Insufficient wallet balance")

        try:
            updated_catalog = await self.db.reward_catalog.update(
                where={
                    "catalog_id":      str(request.catalog_id),
                    "available_stock": {"gt": 0},
                },
                data={
                    "available_stock": {"decrement": 1},
                    "updated_at":      datetime.now(timezone.utc),
                    "updated_by":      granted_by_user_id,
                },
            )
            if not updated_catalog:
                raise HTTPException(status_code=400,
                    detail="Out of stock! This reward was just claimed by someone else.")

            history_record = None
            async with audit_ctx(
                user_id    = granted_by_user_id,
                request    = req_info,        # ← FIXED: was request=None, now passes HTTP request
                table_name = "reward_history",
                record_id  = lambda: str(history_record.history_id),
                operation  = "REDEEM",
                new_values = lambda: {
                    "wallet_id":  str(wallet_id),
                    "catalog_id": str(request.catalog_id),
                    "points":     request.points,
                    "granted_by": granted_by_user_id,
                },
            ):
                history_record = await self.db.reward_history.create(
                    data={
                        "wallet_id":  str(wallet_id),
                        "catalog_id": str(request.catalog_id),
                        "points":     request.points,
                        "granted_by": granted_by_user_id,
                        "comment":    request.comment,
                        "created_by": granted_by_user_id,
                        "updated_by": granted_by_user_id,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("grant_reward DB write failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Transaction failed: {str(e)}")

        # Extract IP to forward through the stream so wallet consumer can audit it
        _ip = req_info.client.host if req_info and req_info.client else ""

        from src.common.event_publisher import publish
        await publish("events:reward.redeemed", {
            "history_id":  str(history_record.history_id),
            "wallet_id":   str(wallet_id),
            "points":      str(request.points),
            "catalog_id":  str(request.catalog_id),
            "redeemed_by": granted_by_user_id,
            "ip_address":  _ip,              # ← ADDED: forwarded to wallet consumer
        })

        await invalidate_catalog()
        await invalidate_history(str(wallet_id))

        try:
            employee_id = wallet_data.get("employee_id")
            if employee_id:
                await self._notif.create_notification(
                    employee_id=employee_id,
                    title=f"You redeemed \"{reward_item.reward_name}\"",
                    message=(
                        f"{request.points} points were used to redeem "
                        f"\"{reward_item.reward_name}\"."
                        + (f" Note: {request.comment}" if request.comment else "")
                    ),
                    type=NotificationType.REWARD,
                )
        except Exception:
            logger.exception("Redemption notification failed — redemption succeeded")

        logger.info("Reward redeemed: catalog=%s wallet=%s points=%d",
                    request.catalog_id, wallet_id, request.points)
        return {
            "history_id":      history_record.history_id,
            "points":          history_record.points,
            "granted_at":      history_record.granted_at,
            "status":          "COMPLETED",
            "new_stock_level": updated_catalog.available_stock,
            "new_balance":     available_points - request.points,
        }

    # ── History ───────────────────────────────────────────────────────────────

    async def get_history(self, wallet_id: Optional[str] = None, page: int = 1, size: int = 10):
        if wallet_id:
            try:
                await internal_client.get_wallet_by_id(wallet_id)
            except HTTPException as exc:
                if exc.status_code == 404:
                    raise HTTPException(status_code=404, detail="Wallet not found.")
                raise

        key    = _key_history(wallet_id, page, size)
        cached = await cache_get(key, l1_ttl=L1_VOLATILE)
        if cached is not None:
            return cached

        skip_count   = (page - 1) * size
        where_clause = {}
        if wallet_id:
            where_clause["wallet_id"] = wallet_id

        history = await self.db.reward_history.find_many(
            where=where_clause, skip=skip_count, take=size,
            order={"granted_at": "desc"},
            include={
                "reward_catalog": True,
                "employees_reward_history_granted_byToemployees": True,
            },
        )
        total_items = await self.db.reward_history.count(where=where_clause)
        result = {
            "data":        [h.model_dump() for h in history],
            "total_items": total_items,
            "page":        page,
            "size":        size,
        }
        await cache_set(key, result, ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
        return {**result, "data": history}

    async def get_wallet_id_for_user(self, employee_id: str) -> Optional[str]:
        key    = _key_wallet_id(employee_id)
        cached = await cache_get(key, l1_ttl=L1_PERMANENT)
        if cached is not None:
            return cached
        try:
            data      = await internal_client.get_wallet_by_employee(employee_id)
            wallet_id = data.get("wallet_id")
        except Exception as exc:
            logger.warning("Could not fetch wallet for employee %s: %s", employee_id, exc)
            return None
        if wallet_id:
            await cache_set(key, wallet_id, ttl=TTL_PERMANENT, l1_ttl=L1_PERMANENT)
        return wallet_id