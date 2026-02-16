from pydantic import BaseModel, EmailStr
from typing import Optional, List
from uuid import UUID


# --- Shared Models ---
class EmployeeResponse(BaseModel):
    employee_id: UUID
    username: str
    email: EmailStr
    designation_id: Optional[UUID] = None
    department_id: Optional[UUID] = None

    class Config:
        from_attributes = True


# --- Request Schemas ---
class SignUpRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    designation_id: UUID
    department_id: UUID
    manager_id: Optional[UUID] = None


class LoginRequest(BaseModel):
    username: str   # accepts username or email (handled in service)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenValidationRequest(BaseModel):
    token: str


# --- Response Schemas ---
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    employee: EmployeeResponse


class TokenValidationResponse(BaseModel):
    """Response schema for token validation"""
    valid: bool
    user_id: Optional[str] = None
    email: Optional[str] = None
    roles: Optional[List[str]] = None
    department_id: Optional[str] = None
    error: Optional[str] = None