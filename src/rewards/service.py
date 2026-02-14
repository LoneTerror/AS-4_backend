import json
from fastapi import HTTPException, status, Request
from prisma import Prisma, Json
from uuid import UUID
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone 
from . import schemas

class RewardService:
    def __init__(self, db: Prisma):
        self.db = db

    # ==========================================
    # 🕵️ AUDIT LOG HELPER (Private Method)
    # ==========================================
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
        """
        Writes a record to the audit_log table.
        We use Json.dumps() to ensure dictionaries are stored correctly.
        """
        try:
            await self.db.audit_log.create(
                data={
                    "table_name": table_name,
                    "record_id": record_id,
                    "operation_type": operation,
                    "performed_by": user_id,
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                    # Prisma handles Dict -> Json conversion automatically
                    "old_values": Json(old_values) if old_values else Json({}),
                    "new_values": Json(new_values) if new_values else Json({})
                }
            )
        except Exception as e:
            # ⚠️ rigorous logging should go here. 
            # We don't want the whole API to fail just because the audit log failed.
            print(f"FAILED TO AUDIT LOG: {e}")

    # ==========================================
    # 1. CATEGORY MANAGEMENT
    # ==========================================
    async def create_category(self, request: schemas.CreateCategoryRequest, user_id: str, req_info: Request):
        # Check for duplicate code
        existing = await self.db.reward_categories.find_unique(
            where={"category_code": request.category_code}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Category code already exists")

        new_category =  await self.db.reward_categories.create(
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
            table_name="reward_categories",
            record_id=new_category.category_id,
            operation="INSERT",
            user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            new_values=new_category.model_dump()
        )

        return new_category

    async def get_categories(self, active_only: bool = True):
        where_clause = {"is_active": True} if active_only else {}
        return await self.db.reward_categories.find_many(where=where_clause)
    
    # ==========================================
    # UPDATE CATEGORY
    # ==========================================
    async def update_category(self, category_id: str, request: schemas.UpdateCategoryRequest, user_id: str, req_info: Request):
        # 1. Check if category exists
        existing = await self.db.reward_categories.find_unique(
            where={"category_id": category_id}
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")

        # 2. Prepare update data (remove None values)
        # exclude_unset=True ensures we only update fields the user actually sent
        update_data = request.model_dump(exclude_unset=True)
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        # 3. Add system fields
        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_category =  await self.db.reward_categories.update(
            where={"category_id": category_id},
            data=update_data
        )

        await self._log_change(
            table_name="reward_categories",
            record_id=category_id,
            operation="UPDATE",
            user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            old_values=existing.model_dump(),     # <--- The snapshot BEFORE update
            new_values=updated_category.model_dump() # <--- The snapshot AFTER update
        )

        return updated_category

    # ==========================================
    # 2. CATALOG MANAGEMENT
    # ==========================================
    async def create_item(self, item: schemas.CreateRewardRequest, user_id: str, req_info: Request):
        # 1. Verify Category Exists
        category = await self.db.reward_categories.find_unique(
            where={"category_id": str(item.category_id)}
        )
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        # 2. Check for duplicate Reward Code
        existing = await self.db.reward_catalog.find_unique(
            where={"reward_code": item.reward_code}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Reward code already exists")

        # 3. Create the Reward Configuration
        new_item =  await self.db.reward_catalog.create(
            data={
                "reward_name": item.reward_name,
                "reward_code": item.reward_code,
                "description": item.description,
                "category_id": str(item.category_id),
                "default_points": item.default_points,
                "min_points": item.min_points,
                "max_points": item.max_points,
                "created_by": user_id,
                "updated_by": user_id,
                "updated_at": datetime.now(timezone.utc) 
            }
        )

        await self._log_change(
            table_name="reward_catalog",
            record_id=new_item.catalog_id,
            operation="INSERT",
            user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            new_values=new_item.model_dump()
        )

        return new_item

    async def get_catalog(self, active_only: bool = True):
        where_clause = {"is_active": True} if active_only else {}
        return await self.db.reward_catalog.find_many(where=where_clause)
    
    # ==========================================
    # UPDATE REWARD ITEM
    # ==========================================
    async def update_item(self, catalog_id: str, request: schemas.UpdateRewardRequest, user_id: str, req_info: Request):
        # 1. Check if item exists
        existing_item = await self.db.reward_catalog.find_unique(
            where={"catalog_id": catalog_id}
        )
        if not existing_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        # 2. Logic Check: Min/Max Points Integrity
        # If user updates points, we must ensure min <= max
        new_min = request.min_points if request.min_points is not None else existing_item.min_points
        new_max = request.max_points if request.max_points is not None else existing_item.max_points
        
        if new_min > new_max:
            raise HTTPException(status_code=400, detail=f"Min points ({new_min}) cannot be greater than Max points ({new_max})")

        # 3. Prepare update data
        update_data = request.model_dump(exclude_unset=True)

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        # 4. Add system fields
        update_data["updated_by"] = user_id
        update_data["updated_at"] = datetime.now(timezone.utc)

        updated_item =  await self.db.reward_catalog.update(
            where={"catalog_id": catalog_id},
            data=update_data
        )

        await self._log_change(
            table_name="reward_catalog",
            record_id=catalog_id,
            operation="UPDATE",
            user_id=user_id,
            ip_address=req_info.client.host,
            user_agent=req_info.headers.get("user-agent"),
            old_values=existing_item.model_dump(),
            new_values=updated_item.model_dump()
        )

        return updated_item

    # ==========================================
    # 3. HISTORY & GRANTING LOGIC
    # ==========================================
    async def grant_reward(self, request: schemas.GrantRewardRequest, granted_by_user_id: str):
        """
        Handles the logic when a reward is given to a wallet.
        """
        
        # 1. Fetch the Reward Configuration
        reward_item = await self.db.reward_catalog.find_unique(
            where={"catalog_id": str(request.catalog_id)}
        )
        if not reward_item:
            raise HTTPException(status_code=404, detail="Reward item not found")

        if not reward_item.is_active:
            raise HTTPException(status_code=400, detail="This reward is currently inactive")

        # 2. Validate Point Limits
        if request.points < reward_item.min_points:
            raise HTTPException(
                status_code=400, 
                detail=f"Points must be at least {reward_item.min_points}"
            )
        if request.points > reward_item.max_points:
            raise HTTPException(
                status_code=400, 
                detail=f"Points cannot exceed {reward_item.max_points}"
            )

        # 3. Verify Wallet Exists
        wallet = await self.db.wallets.find_unique(
            where={"wallet_id": str(request.wallet_id)}
        )
        if not wallet:
            raise HTTPException(status_code=404, detail="Recipient wallet not found")

        # 4. Create History Record
        try:
            return await self.db.reward_history.create(
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
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to grant reward: {str(e)}")
        
    async def get_history(
        self, 
        wallet_id: Optional[str] = None, 
        page: int = 1, 
        size: int = 10
    ):
        skip_count = (page - 1) * size
        
        # Build the filter dynamically
        where_clause = {}
        if wallet_id:
            where_clause["wallet_id"] = wallet_id

        # Fetch data with relations (include names!)
        history = await self.db.reward_history.find_many(
            where=where_clause,
            skip=skip_count,
            take=size,
            order={"granted_at": "desc"}, # Newest first
            include={
                "reward_catalog": True, # Get Reward Name
                "employees_reward_history_granted_byToemployees": True # Get Sender Name
            }
        )
        
        # Count total for pagination
        total_items = await self.db.reward_history.count(where=where_clause)
        
        return {
            "data": history,
            "total_items": total_items,
            "page": page,
            "size": size
        }

    async def get_wallet_id_for_user(self, user_id: str) -> Optional[str]:
        """Helper to find a user's wallet ID using their User ID"""
        wallet = await self.db.wallets.find_first(
            where={"employee_id": user_id}
        )
        return wallet.wallet_id if wallet else None