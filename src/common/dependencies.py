# src/common/dependencies.py

import os
import uuid
import hashlib
import httpx
from typing import List, Optional
from fastapi import Depends, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from prisma import Prisma
from jose import jwt, JWTError, ExpiredSignatureError

from src.prisma.client import db
from src.common.cache import cache_get, cache_set

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

security = HTTPBearer(auto_error=False)
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")

# ── How long to cache a validated token result ────────────────────────────────
# JWTs are stateless — a token valid at time T stays valid until its exp claim.
# Caching for 30s means a revoked/expired token can still work for up to 30s.
# Safe for this system; lower to 10s if you need tighter revocation guarantees.
_AUTH_CACHE_TTL = 30
# ─────────────────────────────────────────────────────────────────────────────


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
    """Call this in your lifespan shutdown to cleanly close pooled connections."""
    global _auth_client
    if _auth_client and not _auth_client.is_closed:
        await _auth_client.aclose()
        _auth_client = None


# ─────────────────────────────────────────────────────────────────────────────


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
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

    # ── Cache lookup ──────────────────────────────────────────────────────────
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    cache_key  = f"auth:token:{token_hash}"

    try:
        # Wrap cache_get so a frozen Redis doesn't block the request forever
        import asyncio
        cached = await asyncio.wait_for(cache_get(cache_key), timeout=2.0)
        if cached is not None:
            return CurrentUser(**cached)
    except Exception as cache_err:
        from src.core.logger import logger
        logger.debug(f"[{request_id}] Cache lookup skipped/failed: {cache_err}")
    # ─────────────────────────────────────────────────────────────────────────

    try:
        # 1. PRIMARY: Try calling the Auth Service API
        client   = get_auth_client()
        response = await client.post(
            AUTH_SERVICE_URL,
            json={"token": token},
            headers={"X-Request-ID": request_id},
        )

        if response.status_code != 200 or not response.json().get("valid"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Invalid or expired authentication token")

        data = response.json()
        roles = [r.upper() for r in data.get("roles", [])]
        user  = CurrentUser(
            id=data["user_id"],
            email=data.get("email", ""),
            roles=roles,
            department_id=data.get("department_id"),
        )

        # Cache the validated result
        try:
            await cache_set(cache_key, user.model_dump(), ttl=_AUTH_CACHE_TTL)
        except Exception:
            pass # Ignore caching errors if Redis is down

        return user

    except httpx.RequestError as e:
        # 2. FALLBACK: Auth Service is unreachable (Redis timeout, container crash, etc.)
        from src.core.logger import logger
        logger.warning(f"[{request_id}] Auth service unreachable, falling back to local JWT validation. ({e})")
        
        try:
            # Mathematically verify the token signature using python-jose
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            
            # Extract user ID (handling both 'user_id' and standard 'sub' claims)
            user_id = payload.get("user_id") or payload.get("sub")
            if not user_id:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

            roles = [r.upper() for r in payload.get("roles", [])]
            fallback_user = CurrentUser(
                id=str(user_id), 
                email=payload.get("email", ""),
                roles=roles,
                department_id=payload.get("department_id")
            )
            return fallback_user
            
        except ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature")
        except HTTPException:
            raise
        except Exception as fallback_err:
            logger.error(f"[{request_id}] Fallback validation failed: {fallback_err}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
                detail="Authentication service unavailable"
            )
        

async def check_route_permission(
    request:      Request,
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """
    Checks that the authenticated user has a role permitted to access the
    matched route. Uses the route *template* (e.g. /v1/roles/{role_id}) so
    that parameterised paths resolve correctly against the DB records.
    SUPER_ADMIN bypasses all permission checks.

    Route permissions are cached under "roles:route_permissions" (MEDIUM tier,
    3600s L2 / 300s L1) — invalidated by route_registry on every startup and
    by any route_permission write. DB is only hit on a full cache miss.
    """

    if "SUPER_ADMIN" in current_user.roles:
        return current_user

    matched_route = request.scope.get("route")
    if isinstance(matched_route, APIRoute):
        path_template = matched_route.path
    else:
        path_template = request.scope.get("path", request.url.path)

    route_key = f"{request.method}:{path_template}"

    # ── Cache lookup — keyed per route_key ───────────────────────────────────
    # Stores a list of allowed role_codes for each route.
    # TTL matches MEDIUM tier (L2: 3600s / L1: 300s) — same tier used by
    # route_registry when it invalidates "roles:route_permissions" on startup.
    from src.common.cache import TTL_MEDIUM, L1_MEDIUM
    perm_cache_key = f"roles:route_permissions:{route_key}"
    cached_roles: list[str] | None = await cache_get(perm_cache_key, l1_ttl=L1_MEDIUM)

    if cached_roles is None:
        # Cache miss — fetch from DB and populate cache
        allowed = await db.route_permissions.find_many(
            where={"route_key": route_key},
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
        # Cached empty list means no permissions configured
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No permissions configured for {route_key}",
        )
    # ─────────────────────────────────────────────────────────────────────────

    allowed_role_codes = set(cached_roles)

    if not any(r in allowed_role_codes for r in current_user.roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this operation",
        )

    return current_user


def get_db() -> Prisma:
    return db