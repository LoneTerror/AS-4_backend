"""
src/common/route_registry.py
─────────────────────────────
Auto-registers every route from every microservice into route_permissions
on startup. No manual seeding needed — add a new router endpoint and it
appears in the permissions table automatically.

HOW IT WORKS
────────────
1. Each service calls `register_app_routes(app, default_roles)` in its
   lifespan startup, AFTER DB connects.
2. We walk app.routes, build "METHOD:/path" keys, and upsert them into
   route_permissions for the given default roles.
3. New routes → inserted automatically.
4. Existing routes → skipped (no overwrite — preserves custom role
   assignments made via the UI).
5. Routes removed from code → left in DB as is_active=False so history
   is preserved (you can clean them up manually if needed).

USAGE — add to each service's lifespan:
────────────────────────────────────────
    from src.common.route_registry import register_app_routes

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await connect_redis()

        await register_app_routes(
            app,
            default_roles=["SUPER_ADMIN", "HR_ADMIN"],
            role_overrides=ROLE_OVERRIDES,
            route_titles=ROUTE_TITLES,       # optional but recommended
        )

        yield
        ...

ROLE_OVERRIDES — optional dict to set per-route roles:
────────────────────────────────────────────────────────
    ROLE_OVERRIDES = {
        "GET:/v1/dashboard/leaderboard":    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
        "POST:/v1/rewards/redeem":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    }

ROUTE_TITLES — optional dict to set human-readable display labels:
────────────────────────────────────────────────────────────────────
    ROUTE_TITLES = {
        "GET:/v1/dashboard/leaderboard":    "View Leaderboard",
        "POST:/v1/rewards/redeem":          "Redeem Reward",
    }

    Routes without a title entry get a sensible auto-generated label
    derived from the method + path (e.g. "GET /v1/rewards/catalog"
    becomes "Get Rewards Catalog").

Any route NOT in role_overrides gets default_roles assigned.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.routing import APIRoute

logger = logging.getLogger(__name__)

# ── System routes to always skip ─────────────────────────────────────────────
_SKIP_PATHS = {
    "/health",
    "/v1/docs",
    "/v1/redoc",
    "/v1/openapi.json",
    "/openapi.json",
    "/docs",
    "/redoc",
}

_SYSTEM_ACTOR = None

_REGISTRATION_TIMEOUT_SECONDS = 120


def _auto_title(route_key: str) -> str:
    """
    Derive a human-readable title from a route_key when no explicit title
    is provided.

    Examples:
        "GET:/v1/rewards/catalog"              → "Get Rewards Catalog"
        "POST:/v1/employees/create"            → "Post Employees Create"
        "PATCH:/v1/rewards/catalog/{id}/stock" → "Patch Rewards Catalog Stock"
        "DELETE:/v1/organizations/seasonal-multipliers/{mult_id}" → "Delete Seasonal Multipliers"
    """
    method, _, path = route_key.partition(":")
    # Strip leading slash and split on /
    parts = path.strip("/").split("/")
    # Drop the version segment (v1, v2 …)
    parts = [p for p in parts if not re.fullmatch(r"v\d+", p)]
    # Drop path parameter segments like {employee_id}
    parts = [p for p in parts if not (p.startswith("{") and p.endswith("}"))]
    # Replace hyphens with spaces, title-case each word
    label_parts = " ".join(p.replace("-", " ") for p in parts).title()
    return f"{method.title()} {label_parts}".strip()


def _extract_routes(app: FastAPI) -> list[tuple[str, str]]:
    """
    Walk app.routes and return list of (method, full_path) tuples.
    full_path = app.root_path + route.path  (e.g. /v1/analytics + /dashboard/leaderboard)
    This ensures route_keys in the DB match the keys used in ROLE_OVERRIDES.
    Skips system/doc routes, health checks, and non-API routes.
    """
    # root_path is set via FastAPI(root_path="/v1/service") for reverse-proxy
    # stripping — it is NOT part of route.path, so we prepend it manually.
    root_path = (getattr(app, "root_path", "") or "").rstrip("/")

    # Paths to skip — checked against both the short path and the full path
    _skip_prefixes = ("/docs", "/redoc", "/openapi", "/health")

    results = []
    
    # 1. Grab the root_path defined in your FastAPI app (e.g., "/v1/rewards")
    root = app.root_path.rstrip("/") if app.root_path else ""

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        full_path = root_path + route.path
        # Skip if short path or full path is in the explicit skip set
        if route.path in _SKIP_PATHS or full_path in _SKIP_PATHS:
            continue
        # Skip health and docs regardless of prefix
        if any(route.path.startswith(p) for p in _skip_prefixes):
            continue

        # 2. Glue them together so the DB string matches the real HTTP URL
        full_path = f"{root}/{route.path.lstrip('/')}"

        for method in route.methods or []:
            results.append((method.upper(), full_path))
    return results


async def _do_register(
    app: FastAPI,
    default_roles: list[str],
    role_overrides: dict[str, list[str]],
    route_titles: dict[str, str],
) -> None:
    """Inner registration logic — runs inside an asyncio timeout guard."""
    from src.prisma.client import db

    # Random jitter so all services don't hammer the DB simultaneously.
    jitter = random.uniform(0, 10)
    await asyncio.sleep(jitter)

    # 1. Load all roles from DB into a code→id map
    all_roles = await db.roles.find_many()
    role_map = {r.role_code: r.role_id for r in all_roles}

    if not role_map:
        logger.warning("route_registry: no roles found in DB — skipping route registration")
        return

    # 2. Extract routes from the app
    routes = _extract_routes(app)
    if not routes:
        logger.warning("route_registry: no routes found in app")
        return

    # 3. Bulk-fetch all existing route_permission rows for this service's routes
    route_keys = list({f"{method}:{path}" for method, path in routes})
    existing_rows = await db.route_permissions.find_many(
        where={"route_key": {"in": route_keys}}
    )
    existing_active   = {(r.route_key, r.role_id) for r in existing_rows if r.is_active}
    existing_inactive = {(r.route_key, r.role_id): r for r in existing_rows if not r.is_active}

    inserted    = 0
    reactivated = 0
    skipped     = 0
    errors      = 0

    now = datetime.now(timezone.utc)

    to_insert: list[dict] = []
    to_reactivate: list = []

    for method, path in routes:
        route_key = f"{method}:{path}"
        roles_for_route = role_overrides.get(route_key, default_roles)
        # Use explicit title if provided, otherwise auto-generate one
        title = route_titles.get(route_key) or _auto_title(route_key)

        for role_code in roles_for_route:
            role_id = role_map.get(role_code)
            if not role_id:
                logger.debug(
                    "route_registry: role '%s' not in DB — skipping %s",
                    role_code, route_key,
                )
                continue

            pair = (route_key, role_id)

            if pair in existing_active:
                skipped += 1
            elif pair in existing_inactive:
                to_reactivate.append((existing_inactive[pair], title))
            else:
                to_insert.append({
                    "route_key":  route_key,
                    "title":      title,
                    "role_id":    role_id,
                    "is_active":  True,
                    "created_by": _SYSTEM_ACTOR,
                    "updated_by": _SYSTEM_ACTOR,
                    "updated_at": now,
                })

    # ── Batch insert all new rows in ONE round-trip ───────────────────────────
    if to_insert:
        try:
            result = await db.route_permissions.create_many(
                data=to_insert,
                skip_duplicates=True,
            )
            inserted = result.count if hasattr(result, "count") else len(to_insert)
            logger.debug("route_registry: batch-inserted %d rows", inserted)
        except Exception as insert_err:
            errors += len(to_insert)
            logger.warning("route_registry: batch insert failed: %s", insert_err)

    # ── Reactivate previously-deactivated rows ────────────────────────────────
    for row, title in to_reactivate:
        try:
            await db.route_permissions.update(
                where={"id": row.id},
                data={
                    "is_active":  True,
                    "title":      title,
                    "updated_by": _SYSTEM_ACTOR,
                    "updated_at": now,
                },
            )
            reactivated += 1
            logger.debug("route_registry: re-activated %s", row.route_key)
        except Exception as err:
            errors += 1
            logger.warning("route_registry: reactivation failed for %s: %s", row.route_key, err)

    # ── Invalidate permissions cache ──────────────────────────────────────────
    try:
        from src.common.cache import cache_delete
        await cache_delete("roles:route_permissions")
        logger.debug("route_registry: cache invalidated")
    except Exception as cache_err:
        logger.warning("route_registry: cache invalidation failed: %s", cache_err)

    logger.info(
        "route_registry: %d routes found | %d inserted | %d re-activated | %d already active | %d errors",
        len(routes), inserted, reactivated, skipped, errors,
    )
    if inserted or reactivated:
        logger.info("route_registry: new routes are live immediately (cache cleared)")


async def register_app_routes(
    app: FastAPI,
    default_roles: list[str],
    role_overrides: Optional[dict[str, list[str]]] = None,
    route_titles: Optional[dict[str, str]] = None,
) -> None:
    """
    Auto-register all routes from `app` into route_permissions.

    Non-fatal — if registration times out or fails for any reason, the
    service still starts normally.

    Args:
        app:            The FastAPI app instance for this service.
        default_roles:  Role codes assigned to routes not in role_overrides.
        role_overrides: Optional dict of {route_key: [role_codes]} for
                        routes that need non-default access.
        route_titles:   Optional dict of {route_key: "Human Readable Title"}.
                        Routes without an entry get an auto-generated title.
    """
    role_overrides = role_overrides or {}
    route_titles   = route_titles   or {}

    try:
        await asyncio.wait_for(
            _do_register(app, default_roles, role_overrides, route_titles),
            timeout=_REGISTRATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "route_registry: registration timed out after %ds — service starting without "
            "full route seeding. Routes will be registered on next restart.",
            _REGISTRATION_TIMEOUT_SECONDS,
        )
    except Exception as err:
        logger.warning(
            "route_registry: registration failed — service starting without route seeding: %s",
            err,
        )