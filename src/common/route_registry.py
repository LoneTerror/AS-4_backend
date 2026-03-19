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
4. Existing active rows → skipped (preserves custom UI assignments).
5. Existing inactive rows → reactivated.
6. Routes removed from code → left in DB as is_active=False.

ROUTE KEY FORMAT
────────────────
Keys are always:  METHOD:/v1/<service>/<endpoint>
e.g.             GET:/v1/roles/list
                 POST:/v1/rewards/redeem

The key is built as:  f"{METHOD}:{root_path}{route.path}"
where root_path = FastAPI(root_path="/v1/roles") — the reverse-proxy prefix.
route.path is the bare path registered on the router, e.g. "/list".

Your ROLE_OVERRIDES and ROUTE_TITLES dicts MUST use this same format.

IMPORTANT — DB UNIQUE CONSTRAINT REQUIRED
──────────────────────────────────────────
route_permissions must have a unique index on (route_key, role_id).
Without it, skip_duplicates=True in create_many is a no-op and you will
get duplicate rows on every restart.

Add to your Prisma schema:
    @@unique([route_key, role_id])

Then run:  prisma migrate dev

USAGE
──────
    from src.common.route_registry import register_app_routes

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await db.connect()
        await connect_redis()

        await register_app_routes(
            app,
            default_roles=["SUPER_ADMIN", "HR_ADMIN"],
            role_overrides=ROLE_OVERRIDES,
            route_titles=ROUTE_TITLES,
        )
        yield
        ...

ROLE_OVERRIDES — per-route role lists (optional):
    ROLE_OVERRIDES = {
        "GET:/v1/dashboard/leaderboard": ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
        "POST:/v1/rewards/redeem":       ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    }

ROUTE_TITLES — human-readable labels (optional, auto-generated if absent):
    ROUTE_TITLES = {
        "GET:/v1/dashboard/leaderboard": "View Leaderboard",
        "POST:/v1/rewards/redeem":       "Redeem Reward",
    }
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
_SKIP_EXACT: set[str] = {
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/docs",
    "/v1/redoc",
    "/v1/openapi.json",
}

_SKIP_PREFIXES: tuple[str, ...] = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi",
    "/internal",
)

_SYSTEM_ACTOR = None
_REGISTRATION_TIMEOUT_SECONDS = 120


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auto_title(route_key: str) -> str:
    """
    Derive a human-readable title from a route key.

    Examples:
        "GET:/v1/rewards/catalog"               → "Get Rewards Catalog"
        "POST:/v1/employees/create"             → "Post Employees Create"
        "PATCH:/v1/rewards/catalog/{id}/stock"  → "Patch Rewards Catalog Stock"
        "DELETE:/v1/orgs/seasonal-multipliers/{id}" → "Delete Orgs Seasonal Multipliers"
    """
    method, _, path = route_key.partition(":")
    parts = path.strip("/").split("/")
    # Drop version segments (v1, v2 …)
    parts = [p for p in parts if not re.fullmatch(r"v\d+", p)]
    # Drop path parameter segments like {employee_id}
    parts = [p for p in parts if not (p.startswith("{") and p.endswith("}"))]
    label = " ".join(p.replace("-", " ") for p in parts).title()
    return f"{method.title()} {label}".strip()


def _extract_routes(
    app: FastAPI,
    always_public_routes: set[str],
) -> list[tuple[str, str]]:
    """
    Walk app.routes and return a DEDUPLICATED list of (METHOD, full_path) tuples.

    full_path = root_path + route.path
    e.g. root_path="/v1/roles", route.path="/list"  →  "/v1/roles/list"

    FastAPI's root_path is the reverse-proxy prefix. It is NOT automatically
    prepended to route.path at the ASGI level — we do it here so the route
    keys stored in the DB match the paths as seen by the gateway/client.

    Routes whose full route key (METHOD:full_path) is in always_public_routes
    are skipped — they are never written to route_permissions and bypass
    permission checks entirely (handled in dependencies._is_public).

    Deduplication: FastAPI sometimes surfaces the same APIRoute twice (e.g.
    when a router is included multiple times, or HEAD is paired with GET).
    We use a set to guarantee uniqueness.
    """
    root_path = (getattr(app, "root_path", "") or "").rstrip("/")

    seen: set[tuple[str, str]] = set()
    results: list[tuple[str, str]] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        short_path = route.path  # e.g. "/list"
        full_path  = root_path + short_path  # e.g. "/v1/roles/list"

        # Skip system/utility routes
        if short_path in _SKIP_EXACT or full_path in _SKIP_EXACT:
            continue
        if any(short_path.startswith(p) for p in _SKIP_PREFIXES):
            continue
        if any(full_path.startswith(p) for p in _SKIP_PREFIXES):
            continue

        for method in sorted(route.methods or []):
            method = method.upper()
            # Skip HEAD — it's auto-added by FastAPI alongside GET and is not
            # a distinct permission boundary.
            if method == "HEAD":
                continue
            # Skip routes declared as always-public — they need no DB entry.
            route_key = f"{method}:{full_path}"
            if route_key in always_public_routes:
                continue
            pair = (method, full_path)
            if pair not in seen:
                seen.add(pair)
                results.append(pair)

    return results


# ── Core registration logic ───────────────────────────────────────────────────

async def _do_register(
    app: FastAPI,
    default_roles: list[str],
    role_overrides: dict[str, list[str]],
    route_titles: dict[str, str],
    always_public_routes: set[str],
) -> None:
    """Inner registration — runs inside an asyncio.wait_for timeout guard."""
    from src.prisma.client import db

    # Stagger startup so multiple services don't all hit the DB at t=0.
    jitter = random.uniform(0, 5)
    await asyncio.sleep(jitter)

    # ── 1. Load roles ─────────────────────────────────────────────────────────
    all_roles = await db.roles.find_many()
    role_map: dict[str, str] = {r.role_code: r.role_id for r in all_roles}

    if not role_map:
        logger.warning("route_registry: no roles in DB — skipping registration")
        return

    # ── 1b. Deactivate stale rows for always-public routes ────────────────────
    # These should never have been registered; clean them up if they exist.
    if always_public_routes:
        stale = await db.route_permissions.find_many(
            where={"route_key": {"in": list(always_public_routes)}, "is_active": True}
        )
        if stale:
            for row in stale:
                await db.route_permissions.update(
                    where={"id": row.id},
                    data={"is_active": False, "updated_by": _SYSTEM_ACTOR, "updated_at": datetime.now(timezone.utc)},
                )
            logger.info(
                "route_registry: deactivated %d stale permission rows for always-public routes",
                len(stale),
            )

    # ── 1c. Deactivate stale rows for internal routes ─────────────────────────
    # Internal routes (e.g. /internal/wallets/stats) are service-to-service
    # only — they must never appear in route_permissions or the admin UI.
    # This cleans up any rows that were inserted before _SKIP_PREFIXES included
    # "/internal", so a DB wipe is not required after deploying the fix.
    stale_internal = await db.route_permissions.find_many(
        where={"route_key": {"contains": "/internal/"}, "is_active": True}
    )
    if stale_internal:
        for row in stale_internal:
            await db.route_permissions.update(
                where={"id": row.id},
                data={"is_active": False, "updated_by": _SYSTEM_ACTOR, "updated_at": datetime.now(timezone.utc)},
            )
        logger.info(
            "route_registry: deactivated %d stale internal route permission rows",
            len(stale_internal),
        )

    # ── 2. Extract routes (deduplicated, always_public + internal excluded) ───
    routes = _extract_routes(app, always_public_routes)
    if not routes:
        logger.warning("route_registry: no routes found in app")
        return

    logger.info("route_registry: found %d unique route+method pairs", len(routes))

    # ── 3. Fetch existing rows for these route keys ───────────────────────────
    route_keys = list({f"{method}:{path}" for method, path in routes})
    existing_rows = await db.route_permissions.find_many(
        where={"route_key": {"in": route_keys}}
    )

    # Build lookup sets — (route_key, role_id) → row
    existing_active:   set[tuple[str, str]]         = set()
    existing_inactive: dict[tuple[str, str], object] = {}

    for row in existing_rows:
        pair = (row.route_key, row.role_id)
        if row.is_active:
            existing_active.add(pair)
        else:
            # If somehow there are duplicate inactive rows, keep the latest one
            if pair not in existing_inactive:
                existing_inactive[pair] = row

    # ── 4. Build insert / reactivate batches ──────────────────────────────────
    now = datetime.now(timezone.utc)

    to_insert:     list[dict] = []
    to_reactivate: list[tuple[object, str]] = []

    # Track which (route_key, role_id) pairs we've already queued to avoid
    # inserting duplicates within the same batch (possible if a route somehow
    # appears in _extract_routes twice despite dedup — defensive guard).
    queued: set[tuple[str, str]] = set()

    for method, path in routes:
        route_key       = f"{method}:{path}"
        roles_for_route = role_overrides.get(route_key, default_roles)
        title           = route_titles.get(route_key) or _auto_title(route_key)

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
                # Already live — nothing to do. Title updates are intentionally
                # not overwritten here to preserve admin UI edits.
                continue
            elif pair in existing_inactive:
                if pair not in queued:
                    to_reactivate.append((existing_inactive[pair], title))
                    queued.add(pair)
            else:
                if pair not in queued:
                    to_insert.append({
                        "route_key":  route_key,
                        "title":      title,
                        "role_id":    role_id,
                        "is_active":  True,
                        "created_by": _SYSTEM_ACTOR,
                        "updated_by": _SYSTEM_ACTOR,
                        "updated_at": now,
                    })
                    queued.add(pair)

    # ── 5. Batch insert ───────────────────────────────────────────────────────
    inserted = 0
    if to_insert:
        try:
            # skip_duplicates relies on the @@unique([route_key, role_id])
            # constraint in your Prisma schema.  Without that constraint this
            # is a no-op and duplicates WILL be created. See module docstring.
            result   = await db.route_permissions.create_many(
                data=to_insert,
                skip_duplicates=True,
            )
            inserted = result.count if hasattr(result, "count") else len(to_insert)
            logger.debug("route_registry: batch-inserted %d rows", inserted)
        except Exception as err:
            logger.warning("route_registry: batch insert failed: %s", err)

    # ── 6. Reactivate previously-deactivated rows ─────────────────────────────
    reactivated = 0
    errors      = 0
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
        except Exception as err:
            errors += 1
            logger.warning("route_registry: reactivation failed for %s: %s", row.route_key, err)

    skipped = len(routes) * len(default_roles) - inserted - reactivated - errors

    # ── 7. Invalidate permissions cache ───────────────────────────────────────
    try:
        from src.common.cache import cache_delete
        await cache_delete("roles:route_permissions")
        logger.debug("route_registry: cache invalidated")
    except Exception as err:
        logger.warning("route_registry: cache invalidation failed: %s", err)

    logger.info(
        "route_registry done — routes=%d | inserted=%d | reactivated=%d | skipped=%d | errors=%d",
        len(routes), inserted, reactivated, skipped, errors,
    )


# ── Public API ────────────────────────────────────────────────────────────────

async def register_app_routes(
    app: FastAPI,
    default_roles: list[str],
    role_overrides: Optional[dict[str, list[str]]] = None,
    route_titles: Optional[dict[str, str]] = None,
    always_public_routes: Optional[set[str]] = None,
) -> None:
    """
    Auto-register all routes from `app` into route_permissions.

    Non-fatal — if registration times out or fails, the service still starts.

    Args:
        app:                  The FastAPI app instance for this service.
        default_roles:        Role codes assigned to any route not in role_overrides.
        role_overrides:       {route_key: [role_codes]} for per-route overrides.
        route_titles:         {route_key: "Human Readable Title"}.
                              Routes without an entry get an auto-generated label.
        always_public_routes: Set of route keys (e.g. "POST:/v1/auth/login") that
                              are unconditionally public. These are NEVER written to
                              route_permissions and any existing stale rows for them
                              are deactivated. Use this for pre-auth endpoints like
                              login, refresh, forgot-password, validate, etc. that
                              must remain accessible to unauthenticated users and
                              must never be togglable by an admin.
    """
    role_overrides        = role_overrides        or {}
    route_titles          = route_titles          or {}
    always_public_routes  = always_public_routes  or set()

    try:
        await asyncio.wait_for(
            _do_register(app, default_roles, role_overrides, route_titles, always_public_routes),
            timeout=_REGISTRATION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "route_registry: timed out after %ds — service starting without full "
            "route seeding. Routes will register on next restart.",
            _REGISTRATION_TIMEOUT_SECONDS,
        )
    except Exception as err:
        logger.warning(
            "route_registry: registration failed — service starting without route seeding: %s",
            err,
        )