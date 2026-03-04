from pydantic import BaseModel, Field, UUID4, field_validator,model_validator
from typing import Optional, List, Any
from datetime import datetime

# CATEGORY SCHEMAS (reward_categories)

class CreateCategoryRequest(BaseModel):
    category_name: str = Field(..., min_length=1, max_length=100)
    # Added regex pattern to only allow letters, numbers, dashes, and underscores
    category_code: str = Field(
        ..., 
        min_length=1, 
        max_length=50, 
        pattern=r'^[a-zA-Z0-9_-]+$',
        description="Unique code (alphanumeric, dashes, underscores only) e.g. 'CAT-GIFT'"
    )
    description: Optional[str] = None

    @field_validator('category_name')
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or just whitespace')
        return v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "category_name": "Gift Cards",
                    "category_code": "GIFT_CARD",
                    "description": "Digital and physical gift cards for top retail stores."
                }
            ]
        }
    }

class UpdateCategoryRequest(BaseModel):
    category_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator('category_name')
    @classmethod
    def check_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError('Category name cannot be empty or just whitespace')
            return v.strip()
        return v

class CategoryResponse(BaseModel):
    category_id: UUID4
    category_name: str
    category_code: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class MinimalCategoryInfo(BaseModel):
    category_id: UUID4
    category_name: str
    category_code: str

    class Config:
        from_attributes = True

#CATALOG SCHEMAS (reward_catalog)

class CreateRewardRequest(BaseModel):
    reward_name: str = Field(..., min_length=1, max_length=200)
    reward_code: str = Field(..., min_length=1, max_length=50, description="Unique SKU e.g. 'REW-AMZ-50'")
    description: Optional[str] = None
    category_id: UUID4
    
    default_points: int = Field(..., gt=0)
    min_points: int = Field(..., gt=0)
    max_points: int = Field(..., gt=0)
    available_stock: Optional[int] = Field(0, ge=0, description="Initial stock count")

    @model_validator(mode='after')
    def check_max_points(self) -> 'CreateRewardRequest':
        if self.max_points < self.min_points:
            raise ValueError('max_points must be greater than or equal to min_points')
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reward_name": "Amazon $50 Gift Card",
                    "reward_code": "AMZ-50-GC",
                    "description": "A $50 digital gift card for Amazon.com purchases.",
                    "category_id": "123e4567-e89b-12d3-a456-426614174000",
                    "default_points": 500,
                    "min_points": 500,
                    "max_points": 500,
                    "available_stock": 100
                }
            ]
        }
    }

class UpdateRewardRequest(BaseModel):
    reward_name: Optional[str] = None
    description: Optional[str] = None
    default_points: Optional[int] = None
    min_points: Optional[int] = None 
    max_points: Optional[int] = None  
    is_active: Optional[bool] = None

class RewardItemResponse(BaseModel):
    catalog_id: UUID4
    reward_name: str
    reward_code: str
    description: Optional[str]
    default_points: int
    min_points: int
    max_points: int
    is_active: bool
    created_at: datetime
    stock_status: str
    available_stock: int

    category: Optional[MinimalCategoryInfo] = None 

    class Config:
        from_attributes = True

class AddStockRequest(BaseModel):
    amount: int = Field(..., gt=0, description="Amount of new stock to add")

    @field_validator('amount')
    @classmethod
    def check_reasonable_amount(cls, v: int) -> int:
        # Example business logic: Prevent accidental massive restocks
        max_restock_limit = 10000 
        if v > max_restock_limit:
            raise ValueError(f'Cannot add more than {max_restock_limit} items in a single transaction.')
        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "amount": 50
                }
            ]
        }
    }

# HISTORY/GRANTING SCHEMAS (reward_history)

class GrantRewardRequest(BaseModel):
    """
    Used when a Manager grants a reward to an Employee OR 
    an Employee claims a specific reward.
    """
    wallet_id: UUID4 
    catalog_id: UUID4
    points: int = Field(..., gt=0, description="Actual points given/redeemed")
    comment: Optional[str] = None

class MinimalCatalogInfo(BaseModel):
    reward_name: str
    reward_code: str

class MinimalEmployeeInfo(BaseModel):
    username: str
    email: Optional[str] = None

class RewardHistoryResponse(BaseModel):
    history_id: UUID4
    points: int
    comment: Optional[str]
    granted_at: datetime

    reward_catalog: Optional[MinimalCatalogInfo] = None
    employees_reward_history_granted_byToemployees: Optional[MinimalEmployeeInfo] = None
    
    class Config:
        from_attributes = True

class RedemptionResponse(BaseModel):
    history_id: UUID4
    points: int
    granted_at: datetime
    status: str
    new_stock_level: Optional[int] = None

    class Config:
        from_attributes = True

class PaginatedHistoryResponse(BaseModel):
    data: List[RewardHistoryResponse]
    total_items: int
    page: int
    size: int

class PaginationMeta(BaseModel):
    current_page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool

# WRAPPER RESPONSE
class PaginatedCatalogResponse(BaseModel):
    data: List[RewardItemResponse]
    pagination: PaginationMeta

class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str  # e.g., "INSUFFICIENT_FUNDS", "OUT_OF_STOCK"
    message: str     # Human readable message
    details: Optional[Any] = None