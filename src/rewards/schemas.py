from pydantic import BaseModel, Field, UUID4, field_validator,model_validator, StrictBool, StrictInt, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

# CATEGORY SCHEMAS (reward_categories)

class CreateCategoryRequest(BaseModel):
    category_name: str = Field(
        ..., 
        min_length=1, 
        max_length=100,
        pattern=r'^[a-zA-Z0-9\s\-_&.,()]+$',
        description="Name of the category. Alphanumeric and basic punctuation only."
    )
    
    # Strictly limits to UPPERCASE letters, numbers, dashes, and underscores
    category_code: str = Field(
        ..., 
        min_length=1, 
        max_length=50, 
        pattern=r'^[A-Z0-9_-]+$',
        description="Unique code (Uppercase alphanumeric, dashes, underscores only) e.g. 'CAT-GIFT'"
    )
    
    # Allows most text but blocks angle brackets < > to prevent basic HTML/XSS injection
    description: Optional[str] = Field(
        None,
        pattern=r'^[^<>]*$',
        description="Optional description. HTML tags are not allowed."
    )

    @field_validator('category_name', 'category_code')
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or just whitespace')
        return v.strip().upper() if v == 'category_code' else v.strip()

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "category_name": "Top Performer",
                    "category_code": "TOP_PERFORMER_01",
                    "description": "Awarded for exceptional quarterly performance."
                }
            ]
        }
    }

class UpdateCategoryRequest(BaseModel):
    category_name: Optional[str] = Field(
        None, 
        min_length=1, 
        max_length=100,
        pattern=r'^[a-zA-Z0-9\s\-_&.,()]+$',
        description="Name of the category. Alphanumeric and basic punctuation only."
    )
    
    description: Optional[str] = Field(
        None,
        pattern=r'^[^<>]*$',
        description="Optional description. HTML tags are not allowed."
    )
    
    # --- FIXED: Enforcing strict JSON boolean ---
    is_active: Optional[StrictBool] = Field(
        None, 
        description="Must be a pure boolean (true/false). Strings like 'true' are rejected."
    )

    @field_validator('category_name')
    @classmethod
    def check_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v or not v.strip():
                raise ValueError('Category name cannot be empty or just whitespace')
            return v.strip()
        return v

    @model_validator(mode='before')
    @classmethod
    def prevent_system_field_updates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            allowed_fields = {'category_name', 'description', 'is_active'}
            extra_fields = [key for key in data.keys() if key not in allowed_fields]
            
            if extra_fields:
                raise ValueError(f"Internal system fields cannot be modified. Invalid fields detected: {', '.join(extra_fields)}")
        return data

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "category_name": "Updated Category Name",
                    "description": "Updated description without HTML tags.",
                    "is_active": False
                }
            ]
        }
    }

class CategoryResponse(BaseModel):
    category_id: UUID4
    category_name: str
    category_code: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class MinimalCategoryInfo(BaseModel):
    category_id: UUID4
    category_name: str
    category_code: str

    model_config = ConfigDict(from_attributes=True)

#CATALOG SCHEMAS (reward_catalog)

class CreateRewardRequest(BaseModel):
    # Prevent empty strings, restrict to safe characters
    reward_name: str = Field(
        ..., 
        min_length=1, 
        max_length=200,
        # Added $, ₹, €, and £ to the allowed character class
        pattern=r'^[a-zA-Z0-9\s\-_&.,()$₹€£]+$',
        description="Name of the reward. Alphanumeric, basic punctuation, and currency symbols only."
    )
    
    # Strict uppercase alphanumeric and dashes/underscores
    reward_code: str = Field(
        ..., 
        min_length=1, 
        max_length=50, 
        pattern=r'^[A-Z0-9_-]+$',
        description="Unique SKU e.g. 'REW-AMZ-50'"
    )
    
    # Optional, but blocks basic HTML/XSS injection
    description: Optional[str] = Field(
        None,
        pattern=r'^[^<>]*$',
        description="Optional description. HTML tags are not allowed."
    )
    
    category_id: UUID4
    
    default_points: StrictInt = Field(..., gt=0)
    min_points: StrictInt = Field(..., gt=0)
    max_points: StrictInt = Field(..., gt=0)
    available_stock: Optional[StrictInt] = Field(0, ge=0, description="Initial stock count")

    @field_validator('reward_name', 'reward_code')
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty or just whitespace')
        
        return v.strip().upper() if v == 'reward_code' else v.strip()

    @field_validator('description')
    @classmethod
    def check_desc_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError('Description cannot be just whitespace')
            return v.strip()
        return v

    @model_validator(mode='after')
    def check_points_logic(self) -> 'CreateRewardRequest':
        # 1. Check if Max is greater than Min
        if self.max_points < self.min_points:
            raise ValueError('max_points must be greater than or equal to min_points')
        
        # 2. Check if Default is within the Min/Max range
        if not (self.min_points <= self.default_points <= self.max_points):
            raise ValueError(
                f'default_points ({self.default_points}) must be between '
                f'min_points ({self.min_points}) and max_points ({self.max_points})'
            )
            
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "reward_name": "Amazon $50 Gift Card",
                    "reward_code": "AMZ_50_GC",
                    "description": "A $50 digital gift card for Amazon.com purchases.",
                    "category_id": "cc0e8400-e29b-41d4-a716-446655440003",
                    "default_points": 500,
                    "min_points": 500,
                    "max_points": 500,
                    "available_stock": 100
                }
            ]
        }
    }

class UpdateRewardRequest(BaseModel):
    reward_name: Optional[str] = Field(
        None, 
        min_length=1, 
        max_length=200,
        pattern=r'^[a-zA-Z0-9\s\-_&.,()]+$',
        description="Name of the reward. Alphanumeric and basic punctuation only."
    )
    
    description: Optional[str] = Field(
        None,
        pattern=r'^[^<>]*$',
        description="Optional description. HTML tags are not allowed."
    )
    
    default_points: StrictInt = Field(..., gt=0)
    min_points: StrictInt = Field(..., gt=0)
    max_points: StrictInt = Field(..., gt=0) 
    
    is_active: Optional[StrictBool] = Field(
        None, 
        description="Must be a pure boolean (true/false). Strings like 'true' are rejected."
    )
    
    category_id: Optional[UUID4] = None

    @field_validator('reward_name')
    @classmethod
    def check_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v or not v.strip():
                raise ValueError('Reward name cannot be empty or just whitespace')
            return v.strip()
        return v

    @field_validator('description')
    @classmethod
    def check_desc_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError('Description cannot be just whitespace')
            return v.strip()
        return v

    @model_validator(mode='before')
    @classmethod
    def prevent_system_field_updates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Explicitly missing 'reward_code' because SKUs should be immutable after creation
            allowed_fields = {
                'reward_name', 'description', 'default_points', 
                'min_points', 'max_points', 'is_active', 'category_id'
            }
            extra_fields = [key for key in data.keys() if key not in allowed_fields]
            
            if extra_fields:
                raise ValueError(f"Internal system fields or immutable fields (like reward_code) cannot be modified. Invalid fields detected: {', '.join(extra_fields)}")
        return data

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "reward_name": "Updated Amazon $50 Gift Card",
                    "description": "Updated description without HTML tags.",
                    "default_points": 550,
                    "is_active": False
                }
            ]
        }
    }

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

    model_config = ConfigDict(from_attributes=True)

class AddStockRequest(BaseModel):
    amount: StrictInt = Field(..., gt=0, description="Amount of new stock to add")

    @field_validator('amount')
    @classmethod
    def check_reasonable_amount(cls, v: int) -> int:
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

class RedeemRewardRequest(BaseModel):
    """
    Used when an Employee claims a specific reward for themselves.
    (wallet_id is omitted; fetched securely from the auth token)
    """
    catalog_id: UUID4
    points: int = Field(..., strict=True, gt=0, description="Actual points redeemed")
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
    
    model_config = ConfigDict(from_attributes=True)

class RedemptionResponse(BaseModel):
    history_id: UUID4
    points: int
    granted_at: datetime
    status: str
    new_stock_level: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

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