import os
import httpx
from typing import List, Callable, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# 1. Setup Security Scheme
security = HTTPBearer()

# 2. Get Auth URL from Environment Variables
# Make sure to set this in your .env file or Docker config!
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8001/auth/verify")

class CurrentUser(BaseModel):
    id: str
    email: str             
    roles: List[str]       
    department_id: Optional[str] = None

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    """
    Validates the authentication token by calling the Auth Service.
    """
    token = credentials.credentials
    request_id = request.headers.get("X-Request-ID")

    try:
        # Call the Auth Service to verify the token
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                AUTH_SERVICE_URL,
                json={"token": token},
                headers={"X-Request-ID": request_id} if request_id else None
            )

        # Handle Auth Service Errors
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )

        data = response.json()

        # Double check validity flag
        if not data.get("valid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )

        # Normalize roles to uppercase
        roles = [r.upper() for r in data.get("roles", [])]

        return CurrentUser(
            id=data["user_id"],
            email=data.get("email", ""), 
            roles=roles,                 
            department_id=data.get("department_id")
        )

    except httpx.RequestError:
        # If Auth Service is down, we can't verify users
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable"
        )

def require_roles(*allowed_roles: str) -> Callable:
    """
    Factory function to check for specific roles.
    Usage: @router.get("/", dependencies=[Depends(require_roles("ADMIN", "HR"))])
    """
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:

        # 🔥 SUPER_ADMIN always allowed
        if "SUPER_ADMIN" in current_user.roles:
            return current_user

        # Normalize allowed roles
        normalized_roles = [role.upper() for role in allowed_roles]

        # Check if user has ANY of the allowed roles
        if not any(role in current_user.roles for role in normalized_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation"
            )

        return current_user

    return role_checker