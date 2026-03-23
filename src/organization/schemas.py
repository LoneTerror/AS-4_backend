from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime


# ─────────────────────────────────────────────
# Shared Nested
# ─────────────────────────────────────────────

class DepartmentTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_type_id: UUID  # Added for dropdown functionality
    type_name: str
    type_code: str


class ManagerBriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    employee_id: UUID
    username: str
    email: Optional[str] = None


class PaginationMeta(BaseModel):
    current_page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


# ─────────────────────────────────────────────
# Department Schemas
# ─────────────────────────────────────────────

class DepartmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_id: UUID
    department_name: str
    department_code: str
    department_type: Optional[DepartmentTypeResponse] = None
    manager: Optional[ManagerBriefResponse] = None
    is_active: bool
    created_at: datetime
    created_by: Optional[UUID] = None
    created_by_info: Optional[ManagerBriefResponse] = None
    updated_by: Optional[UUID] = None
    updated_by_info: Optional[ManagerBriefResponse] = None


class DepartmentListResponse(BaseModel):
    data: List[DepartmentListItem]
    pagination: PaginationMeta
    
class DepartmentDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_id: UUID
    department_name: str
    department_code: str
    department_type: Optional[DepartmentTypeResponse] = None
    manager: Optional[ManagerBriefResponse] = None
    employee_count: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by: Optional[UUID] = None          
    created_by_info: Optional[ManagerBriefResponse] = None   
    updated_by: Optional[UUID] = None        
    updated_by_info: Optional[ManagerBriefResponse] = None      


class CreateDepartmentRequest(BaseModel):
    department_name: str = Field(..., max_length=255)
    department_code: str = Field(..., max_length=20)
    department_type_id: UUID
    manager_id: Optional[UUID] = None

    @field_validator("department_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper()


class UpdateDepartmentRequest(BaseModel):
    department_name: Optional[str] = Field(None, max_length=255)
    department_code: Optional[str] = Field(None, max_length=20)
    department_type_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    is_active: Optional[bool] = None

    @field_validator("department_code")
    @classmethod
    def uppercase_code(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


class DepartmentCreatedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_id: UUID
    department_name: str
    department_code: str
    department_type: Optional[DepartmentTypeResponse] = None
    manager: Optional[ManagerBriefResponse] = None
    is_active: bool
    created_at: datetime
    created_by: Optional[UUID] = None
    created_by_info: Optional[ManagerBriefResponse] = None  


class DepartmentUpdatedResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    department_id: UUID
    department_name: str
    department_code: str
    department_type: Optional[DepartmentTypeResponse] = None
    manager: Optional[ManagerBriefResponse] = None
    is_active: bool
    updated_at: Optional[datetime] = None
    updated_by: Optional[UUID] = None
    updated_by_info: Optional[ManagerBriefResponse] = None   


# ─────────────────────────────────────────────
# Designation Schemas
# ─────────────────────────────────────────────

class DesignationListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    designation_id: UUID
    designation_name: str
    designation_code: str
    level: int
    is_active: bool
    created_at: datetime


class DesignationListResponse(BaseModel):
    data: List[DesignationListItem]
    pagination: PaginationMeta


class DesignationDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    designation_id: UUID
    designation_name: str
    designation_code: str
    level: int
    description: Optional[str] = None
    employee_count: int
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class CreateDesignationRequest(BaseModel):
    designation_name: str = Field(..., max_length=100)
    designation_code: str = Field(..., max_length=50)
    level: int = Field(..., ge=1)
    description: Optional[str] = None

    @field_validator("designation_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.upper()


class UpdateDesignationRequest(BaseModel):
    designation_name: Optional[str] = Field(None, max_length=100)
    designation_code: Optional[str] = Field(None, max_length=50)
    level: Optional[int] = Field(None, ge=1)
    description: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("designation_code")
    @classmethod
    def uppercase_code(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


# ─────────────────────────────────────────────
# 5.5 Status Master Schemas
# ─────────────────────────────────────────────

class StatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    status_id: UUID
    status_code: str
    status_name: str
    description: Optional[str] = None
    entity_type: str
    created_at: datetime


class StatusDetailResponse(StatusResponse):
    updated_at: Optional[datetime] = None


class CreateStatusRequest(BaseModel):
    status_code: str = Field(..., max_length=50)
    status_name: str = Field(..., max_length=100)
    description: Optional[str] = None
    entity_type: str = Field(..., max_length=50)

    @field_validator("status_code")
    @classmethod
    def uppercase_status_code(cls, v: str) -> str:
        return v.upper()

    @field_validator("entity_type")
    @classmethod
    def validate_entity_type(cls, v: str) -> str:
        allowed = {"EMPLOYEE", "REVIEW", "TRANSACTION", "REWARD"}
        if v.upper() not in allowed:
            raise ValueError(f"entity_type must be one of: {', '.join(allowed)}")
        return v.upper()


class UpdateStatusRequest(BaseModel):
    status_name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


# ─────────────────────────────────────────────
# 5.6 Audit Log Schemas
# ─────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    audit_id:       UUID
    table_name:     str
    record_id:      UUID
    operation_type: str
    old_values:     Optional[Any] = None
    new_values:     Optional[Any] = None
    performed_by:   UUID
    performed_at:   datetime
    ip_address:     Optional[str] = None
    user_agent:     Optional[str] = None
    employee_name:  Optional[str] = None  
    employee_email: Optional[str] = None  


class AuditLogListResponse(BaseModel):
    data: List[AuditLogResponse]
    pagination: PaginationMeta