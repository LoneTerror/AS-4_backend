from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from src.auth.schemas import (
    LoginRequest,
    TokenResponse,
    SignUpRequest,
    LogoutRequest,
    RefreshRequest,
    EmployeeResponse,
    TokenValidationRequest,
    TokenValidationResponse
)
from src.auth.service import (
    authenticate_user,
    create_employee,
    logout_user,
    refresh_access_token,
    validate_token
)
from src.auth.dependencies import require_roles
from src.core.security import decode_token

# Used to extract the current user's identity during logout
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """Login endpoint - returns access and refresh tokens"""
    return await authenticate_user(payload.username, payload.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    """Refresh access token using refresh token"""
    return await refresh_access_token(payload.refresh_token)


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    token: str = Depends(oauth2_scheme)
):
    """Logout - revokes the refresh token"""
    # Decode the access token to confirm identity before revoking refresh token
    user_data = decode_token(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid session")

    return await logout_user(payload.refresh_token, user_data["sub"])


@router.post("/signup", response_model=EmployeeResponse)
async def signup(
    payload: SignUpRequest,
    user=Depends(require_roles("SUPER_ADMIN", "HR_ADMIN"))
):
    """Create a new employee - requires SUPER_ADMIN or HR_ADMIN role"""
    return await create_employee(payload, user["sub"])


@router.post("/validate", response_model=TokenValidationResponse)
async def validate_token_endpoint(payload: TokenValidationRequest):
    """
    Validate JWT token - used by other microservices
    This is a public endpoint for inter-service communication
    """
    return await validate_token(payload.token)