from pydantic import BaseModel, EmailStr, StringConstraints, field_validator
from typing import Optional, List, Annotated
from uuid import UUID


class SignUpRequest(BaseModel):
    username: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    email: EmailStr
    password: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    designation_id: UUID
    department_id: UUID
    manager_id: Optional[UUID] = None


# --- Shared Models ---
class EmployeeResponse(BaseModel):
    employee_id: UUID
    username: str
    email: EmailStr
    designation_id: Optional[UUID] = None
    department_id: Optional[UUID] = None

    class Config:
        from_attributes = True





class LoginRequest(BaseModel):
    username: str   # accepts username or email (handled in service)
    password: str

    # ERR-437 FIX: Normalize username to lowercase so that login is
    # case-insensitive. "ADMIN@COMPANY.COM" and "admin@company.com"
    # must resolve to the same account.
    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.strip().lower()


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


class ForgotPasswordRequest(BaseModel):
    """Request schema for forgot password"""
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Response schema for forgot password"""
    message: str


class ResetPasswordRequest(BaseModel):
    """Request schema for password reset"""
    token: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    """Response schema for password reset"""
    message: str