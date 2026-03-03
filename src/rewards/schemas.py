from pydantic import BaseModel, Field, UUID4, validator
from typing import Optional, List, Any
from datetime import datetime

# CATEGORY SCHEMAS (reward_categories)

class CreateCategoryRequest(BaseModel):
    category_name: str = Field(..., max_length=100)
    category_code: str = Field(..., max_length=50, description="Unique code e.g. 'CAT-GIFT'")
    description: Optional[str] = None

class UpdateCategoryRequest(BaseModel):
    category_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None

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
    reward_name: str = Field(..., max_length=200)
    reward_code: str = Field(..., max_length=50, description="Unique SKU e.g. 'REW-AMZ-50'")
    description: Optional[str] = None
    category_id: UUID4
    
    default_points: int = Field(..., gt=0)
    min_points: int = Field(..., gt=0)
    max_points: int = Field(..., gt=0)
    available_stock: Optional[int] = Field(0, ge=0, description="Initial stock count")

    @validator('max_points')
    def check_max_points(cls, v, values):
        if 'min_points' in values and v < values['min_points']:
            raise ValueError('max_points must be greater than or equal to min_points')
        return v

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