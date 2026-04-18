# src/common/dependencies.py

import os
import uuid
import hashlib
import httpx
from typing import List, Optional
from fastapi import Depends, HTTPException, Request, status, Query
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from prisma import Prisma
import jwt  
from jwt.exceptions import PyJWTError, ExpiredSignatureError

from src.prisma.client import db
from src.common.cache import cache_get, cache_set

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM  = os.getenv("ALGORITHM", "HS256")

security        = HTTPBearer(auto_error=False)
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")

_AUTH_CACHE_TTL = 30

# ── Paths that never require authentication ───────────────────────────────────
#
# Seeded with well-known system paths. Each service extends this at startup
# by calling register_public_paths() for its own always-public routes (e.g.
# login, refresh, validate). This prevents those routes from ever being
# checked against route_permissions — they must remain accessible even when
# no valid token exists.
_PUBLIC_PATHS: set[str] = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/docs",
    "/v1/redoc",
    "/v1/openapi.json",
}


def register_public_paths(*paths: str) -> None:
    """
    Declare additional paths that bypass all auth and permission checks.

    Call this once per service at startup (before the first request) for
    any endpoint that must be reachable without a token — e.g. login,
    refresh, forgot-password, validate. These paths are NEVER checked
    against route_permissions so an admin cannot accidentally lock users
    out by toggling them off.

    Paths may be bare (e.g. "/login") or fully qualified with the service
    root_path prefix (e.g. "/aabhar/v1/auth/login") — both forms are registered
    so the check works regardless of how the proxy forwards the request.

    Example (auth main.py lifespan):
        from src.common.dependencies import register_public_paths
        register_public_paths(
            "/login", "/aabhar/v1/auth/login",
            "/refresh", "/aabhar/v1/auth/refresh",
            ...
        )
    """
    _PUBLIC_PATHS.update(paths)


def _is_public(request: Request) -> bool:
    """
    True if this request should bypass all auth and permission checks.
    Uses scope["path"] — the raw ASGI path, unaffected by root_path or
    proxy prefix rewriting — so the check works identically in all envs.
    """
    return request.scope.get("path", request.url.path) in _PUBLIC_PATHS


def _build_route_key(request: Request) -> str:
    """
    Build the route key that matches what route_registry stored in the DB.

    route_registry stores:  f"{METHOD}:{root_path}{route.path}"
    e.g.  GET:/aabhar/v1/analytics/dashboard/leaderboard

    request.scope["route"].path  →  bare template,  e.g. /dashboard/leaderboard
    request.app.root_path        →  proxy prefix,   e.g. /aabhar/v1/analytics

    We must combine them the same way route_registry does, otherwise the
    DB lookup always misses and every non-SUPER_ADMIN gets 403.

    NOTE: request.scope["root_path"] is the ASGI root_path forwarded by the
    proxy and may differ from app.root_path in some deployments.  We use
    app.root_path (set in FastAPI(..., root_path=...)) because that is
    exactly what route_registry reads via getattr(app, "root_path", "").
    """
    matched_route = request.scope.get("route")
    if isinstance(matched_route, APIRoute):
        # Parameterised template: /dashboard/leaderboard or /{employee_id}
        bare_path = matched_route.path
    else:
        # Fallback — should not happen for real API routes
        bare_path = request.scope.get("path", request.url.path)

    # app.root_path is set via FastAPI(root_path="/aabhar/v1/service")
    root_path = (getattr(request.app, "root_path", "") or "").rstrip("/")

    full_path = root_path + bare_path          # e.g. /aabhar/v1/analytics/dashboard/leaderboard
    return f"{request.method.upper()}:{full_path}"  # e.g. GET:/aabhar/v1/analytics/dashboard/leaderboard


# ── Singleton HTTP client ─────────────────────────────────────────────────────
_auth_client: httpx.AsyncClient | None = None


def get_auth_client() -> httpx.AsyncClient:
    global _auth_client
    if _auth_client is None or _auth_client.is_closed:
        _auth_client = httpx.AsyncClient(
            timeout=5.0,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=20,
                keepalive_expiry=30,
            ),
        )
    return _auth_client


async def close_auth_client() -> None:
    global _auth_client
    if _auth_client and not _auth_client.is_closed:
        await _auth_client.aclose()
        _auth_client = None


# ── Models ────────────────────────────────────────────────────────────────────
class CurrentUser(BaseModel):
    id:            str
    email:         str
    roles:         List[str]
    department_id: Optional[str] = None


# Sentinel returned for public paths.
_PUBLIC_USER = CurrentUser(id="system", email="", roles=["PUBLIC"])


# ── Authentication ────────────────────────────────────────────────────────────
async def get_current_user(
    request:     Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CurrentUser:

    if _is_public(request):
        return _PUBLIC_USER

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token      = credentials.credentials
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── Cache lookup ──────────────────────────────────────────────────────────
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    cache_key  = f"auth:token:{token_hash}"

    try:
        import asyncio
        cached = await asyncio.wait_for(cache_get(cache_key), timeout=2.0)
        if cached is not None:
            cached_id = cached.get("id")
            if not cached_id or not isinstance(cached_id, str) or cached_id.lower() == "null":
                from src.common.cache import cache_delete
                await cache_delete(cache_key)
            else:
                return CurrentUser(**{k: v for k, v in cached.items() if k in CurrentUser.model_fields})
    except Exception as cache_err:
        from src.core.logger import logger
        logger.debug(f"[{request_id}] Cache lookup skipped/failed: {cache_err}")

    # ── Auth service validation ───────────────────────────────────────────────
    try:
        client   = get_auth_client()
        response = await client.post(
            AUTH_SERVICE_URL,
            json={"token": token},
            headers={"X-Request-ID": request_id},
        )

        if response.status_code != 200 or not response.json().get("valid"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token",
            )

        data    = response.json()
        user_id = data.get("user_id")

        if not user_id or not isinstance(user_id, str) or user_id.lower() == "null":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing or null user_id",
            )

        roles = [r.upper() for r in data.get("roles", [])]
        user  = CurrentUser(
            id=user_id,
            email=data.get("email", ""),
            roles=roles,
            department_id=data.get("department_id"),
        )

        try:
            await cache_set(cache_key, user.model_dump(), ttl=_AUTH_CACHE_TTL)
        except Exception:
            pass

        return user

    except httpx.RequestError as e:
        from src.core.logger import logger
        logger.warning(
            f"[{request_id}] Auth service unreachable, falling back to local JWT validation. ({e})"
        )

        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("user_id") or payload.get("sub")

            if not user_id or not isinstance(user_id, str) or user_id.lower() == "null":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload: missing or null user_id",
                )

            roles = [r.upper() for r in payload.get("roles", [])]
            return CurrentUser(
                id=str(user_id),
                email=payload.get("email", ""),
                roles=roles,
                department_id=payload.get("department_id"),
            )

        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )
        except PyJWTError: 
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token signature",
            )
        except HTTPException:
            raise
        except Exception as fallback_err:
            from src.core.logger import logger
            logger.error(
                f"[{request_id}] Fallback validation failed: {fallback_err}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable",
            )


# ── Permission check ──────────────────────────────────────────────────────────
async def check_route_permission(
    request:      Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Checks that the authenticated user has a role permitted to access the
    matched route.

    Route key format:  METHOD:/aabhar/v1/<service>/<path_template>
    e.g.               GET:/aabhar/v1/analytics/dashboard/leaderboard
                       GET:/aabhar/v1/employees/{employee_id}

    This MUST match what route_registry stored — built as:
        f"{METHOD}:{app.root_path}{route.path}"

    The previous implementation used bare `matched_route.path` without
    root_path, so "GET:/dashboard/leaderboard" never matched the DB record
    "GET:/aabhar/v1/analytics/dashboard/leaderboard" → every non-SUPER_ADMIN got 403.
    """

    if _is_public(request):
        return current_user

    # SUPER_ADMIN bypasses all permission checks
    if "SUPER_ADMIN" in current_user.roles:
        return current_user

    route_key = _build_route_key(request)

    # ── Cache lookup ──────────────────────────────────────────────────────────
    from src.common.cache import TTL_MEDIUM, L1_MEDIUM
    perm_cache_key  = f"roles:route_permissions:{route_key}"
    cached_roles: list[str] | None = await cache_get(perm_cache_key, l1_ttl=L1_MEDIUM)

    if cached_roles is None:
        allowed = await db.route_permissions.find_many(
            where={"route_key": route_key, "is_active": True},
            include={"roles": True},
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No permissions configured for {route_key}",
            )
        cached_roles = [p.roles.role_code.upper() for p in allowed]
        await cache_set(perm_cache_key, cached_roles, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
    elif not cached_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No permissions configured for {route_key}",
        )

    if not any(r in set(cached_roles) for r in current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )

    return current_user

class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number, must be >= 1"),
        size: int = Query(10, ge=1, le=100, description="Items per page (Max 100)")
    ):
        self.page = page
        self.size = size


def get_db() -> Prisma:
    return db