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
        )

        yield
        ...

ROLE_OVERRIDES — optional dict to set per-route roles:
────────────────────────────────────────────────────────
    ROLE_OVERRIDES = {
        "GET:/v1/dashboard/leaderboard":    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
        "GET:/v1/dashboard/recent-reviews": ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
        "POST:/v1/rewards/redeem":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    }

Any route NOT in role_overrides gets default_roles assigned.
"""

import asyncio
import logging
import random
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

# created_by / updated_by are String? @db.Uuid (nullable) in the schema,
# so we pass None for system-generated rows — no UUID string needed.
_SYSTEM_ACTOR = None

# How long to wait for the entire registration before giving up.
# Service will still start — registration failure is non-fatal.
# Increased from 30s to 120s — all 8 services start simultaneously and
# hammer the DB at once; the previous 30s timeout was too tight.
_REGISTRATION_TIMEOUT_SECONDS = 120


def _extract_routes(app: FastAPI) -> list[tuple[str, str]]:
    """
    Walk app.routes and return list of (method, path) tuples.
    Skips system/doc routes and non-API routes.
    """
    results = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in _SKIP_PATHS:
            continue
        if any(route.path.startswith(skip) for skip in ["/docs", "/redoc", "/openapi"]):
            continue
        for method in route.methods or []:
            results.append((method.upper(), route.path))
    return results


async def _do_register(
    app: FastAPI,
    default_roles: list[str],
    role_overrides: dict[str, list[str]],
) -> None:
    """Inner registration logic — runs inside an asyncio timeout guard."""
    from src.prisma.client import db

    # Random jitter so all 8 services don't hammer the DB simultaneously.
    # Increased from 0–2s to 0–10s to spread the load across services.
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
    #    in ONE query — avoids N×M individual find_first calls under parallel startup.
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

    # Categorise every (route_key, role_id) pair:
    #   to_insert     — brand-new rows  → single create_many call (1 round-trip)
    #   to_reactivate — inactive rows   → individual updates (need row id)
    to_insert: list[dict] = []
    to_reactivate: list = []

    for method, path in routes:
        route_key = f"{method}:{path}"
        roles_for_route = role_overrides.get(route_key, default_roles)

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
                to_reactivate.append(existing_inactive[pair])
            else:
                to_insert.append({
                    "route_key":  route_key,
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
                skip_duplicates=True,  # safe against concurrent service startups
            )
            inserted = result.count if hasattr(result, "count") else len(to_insert)
            logger.debug("route_registry: batch-inserted %d rows", inserted)
        except Exception as insert_err:
            errors += len(to_insert)
            logger.warning("route_registry: batch insert failed: %s", insert_err)

    # ── Reactivate previously-deactivated rows (need per-row id) ─────────────
    for row in to_reactivate:
        try:
            await db.route_permissions.update(
                where={"id": row.id},
                data={
                    "is_active":  True,
                    "updated_by": _SYSTEM_ACTOR,
                    "updated_at": now,
                },
            )
            reactivated += 1
            logger.debug("route_registry: re-activated %s", row.route_key)
        except Exception as err:
            errors += 1
            logger.warning("route_registry: reactivation failed for %s: %s", row.route_key, err)

    # Invalidate the permissions cache so middleware picks up new routes immediately
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
) -> None:
    """
    Auto-register all routes from `app` into route_permissions.

    Non-fatal — if registration times out or fails for any reason, the
    service still starts normally. Routes will be registered on the next
    restart once DB contention clears.

    Args:
        app:            The FastAPI app instance for this service.
        default_roles:  Role codes assigned to routes not in role_overrides.
        role_overrides: Optional dict of {route_key: [role_codes]} for
                        routes that need non-default access.
    """
    role_overrides = role_overrides or {}

    try:
        await asyncio.wait_for(
            _do_register(app, default_roles, role_overrides),
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