"""Authentication dependencies for the analytics service.
Validates tokens via the Auth service (inter-service communication).
"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Callable
import httpx
import os

security = HTTPBearer()

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")


class CurrentUser(BaseModel):
    id: str
    email: str
    roles: List[str]
    department_id: str | None = None


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    """
    Validates the authentication token and returns the current user.

    Raises:
        HTTPException 401: Invalid or expired authentication token
        HTTPException 503: Authentication service unavailable
    """
    token = credentials.credentials
    request_id = request.headers.get("X-Request-ID")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                AUTH_SERVICE_URL,
                json={"token": token},
                headers={"X-Request-ID": request_id} if request_id else None
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )

        data = response.json()

        if not data.get("valid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token"
            )

        roles = [r.upper() for r in data.get("roles", [])]

        return CurrentUser(
            id=data["user_id"],
            email=data["email"],
            roles=roles,
            department_id=data.get("department_id")
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable"
        )


def require_roles(*allowed_roles: str) -> Callable:
    """
    Dependency factory that creates a dependency requiring specific roles.
    SUPER_ADMIN always bypasses role checks.
    """
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:

        if "SUPER_ADMIN" in current_user.roles:
            return current_user

        normalized_roles = [role.upper() for role in allowed_roles]

        if not any(role in current_user.roles for role in normalized_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation"
            )

        return current_user

    return role_checker
