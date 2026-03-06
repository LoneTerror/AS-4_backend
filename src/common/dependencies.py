# src/common/dependencies.py

import os
import uuid
import httpx
from typing import List, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from prisma import Prisma

from src.prisma.client import db

security = HTTPBearer(auto_error=False)
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")


class CurrentUser(BaseModel):
    id:            str
    email:         str
    roles:         List[str]
    department_id: Optional[str] = None


async def get_current_user(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser:

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token      = credentials.credentials
    # Always forward a request ID for traceability — generate one if not provided
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                AUTH_SERVICE_URL,
                json={"token": token},
                headers={"X-Request-ID": request_id},
            )

        if response.status_code != 200:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid or expired authentication token")

        data = response.json()
        if not data.get("valid"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid or expired authentication token")

        roles = [r.upper() for r in data.get("roles", [])]
        return CurrentUser(
            id=data["user_id"],
            email=data.get("email", ""),
            roles=roles,
            department_id=data.get("department_id"),
        )

    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Authentication service unavailable")


async def check_route_permission(
    request:      Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Checks that the authenticated user has a role permitted to access the
    matched route. Uses the route *template* (e.g. /v1/roles/{role_id}) so
    that parameterised paths resolve correctly against the DB records.
    SUPER_ADMIN bypasses all permission checks.
    """

    if "SUPER_ADMIN" in current_user.roles:
        return current_user

    # Use the route template, not the resolved URL, so that paths like
    # /v1/roles/abc-123 correctly match the stored key GET:/v1/roles/{role_id}
    matched_route = request.scope.get("route")
    if isinstance(matched_route, APIRoute):
        path_template = matched_route.path
    else:
        # Fallback for non-APIRoute matches (e.g. Mount, WebSocket)
        path_template = request.scope.get("path", request.url.path)

    route_key = f"{request.method}:{path_template}"

    allowed = await db.route_permissions.find_many(
        where={"route_key": route_key},
        include={"roles": True},
    )

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No permissions configured for {route_key}",
        )

    # Each row has exactly one role (one role_id FK); collect all allowed codes
    allowed_role_codes = {p.roles.role_code.upper() for p in allowed}

    if not any(r in allowed_role_codes for r in current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )

    return current_user


def get_db() -> Prisma:
    return db