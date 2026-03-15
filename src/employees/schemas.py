from pydantic import BaseModel, EmailStr, Field, field_validator, ConfigDict
from typing import Optional, List
from uuid import UUID
from datetime import datetime, date
import re

# --- Nested Response Models ---

class DesignationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True) # V2 Standard
    designation_id: UUID
    designation_name: str
    designation_code: str
    level: int

class DepartmentTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    type_name: str
    type_code: str

class DepartmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_id: UUID
    department_name: str
    department_code: str
    department_type: Optional[DepartmentTypeResponse] = None

class ManagerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: UUID
    username: str
    email: EmailStr

class StatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status_id: UUID
    status_code: str
    status_name: str

class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    wallet_id: UUID
    available_points: int
    redeemed_points: int
    total_earned_points: int
    version: int

class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    role_id: UUID
    role_name: str
    role_code: str

# --- Main Response Models ---

class EmployeeCreatedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: UUID
    username: str
    email: EmailStr
    designation_id: UUID
    department_id: UUID
    manager_id: UUID
    date_of_joining: date
    date_of_birth: Optional[date] = None
    status_id: UUID
    is_active: bool
    wallet: Optional[WalletResponse] = None
    created_at: datetime
    created_by: Optional[UUID] = None

class EmployeeDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: UUID
    username: str
    email: EmailStr
    designation: Optional[DesignationResponse] = None
    department: Optional[DepartmentResponse] = None
    manager: Optional[ManagerResponse] = None
    date_of_joining: date
    date_of_birth: Optional[date] = None
    status: Optional[StatusResponse] = None
    is_active: bool
    wallet: Optional[WalletResponse] = None
    roles: List[RoleResponse] = []
    created_at: datetime
    created_by: Optional[UUID] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[UUID] = None

class EmployeeListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: UUID
    username: str
    email: EmailStr
    designation_id: Optional[UUID] = None
    designation_name: Optional[str] = None
    department_id: Optional[UUID] = None
    department_name: Optional[str] = None
    manager_id: Optional[UUID] = None
    manager_name: Optional[str] = None
    date_of_joining: date
    status_id: Optional[UUID] = None
    status_name: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

class PaginationMeta(BaseModel):
    current_page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool

class EmployeeListResponse(BaseModel):
    data: List[EmployeeListItem]
    pagination: PaginationMeta

# --- Request Models ---

class CreateEmployeeRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    designation_id: UUID
    department_id: UUID
    manager_id: UUID
    date_of_joining: date
    date_of_birth: Optional[date] = None
    status_id: UUID

    @field_validator('date_of_birth')
    @classmethod
    def validate_dob(cls, v: Optional[date]) -> Optional[date]:
        if v is not None and v >= datetime.now().date():
            raise ValueError('Date of birth must be in the past')
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain number')
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
            raise ValueError('Password must contain a special character')
        return v

    @field_validator('date_of_joining')
    @classmethod
    def validate_date(cls, v: date) -> date:
        if v > datetime.now().date():
            raise ValueError('Date of joining cannot be in the future')
        return v

class UpdateEmployeeRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    email: Optional[EmailStr] = None
    designation_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    status_id: Optional[UUID] = None
    date_of_birth: Optional[date] = None