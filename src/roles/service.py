# src/roles/service.py
from datetime import datetime, timezone
from fastapi import HTTPException, Request
from typing import Optional

from src.prisma.client import db
from src.common.audit import audit_ctx
from src.common.dependencies import CurrentUser
from src.common.cache import (
    cache_get, cache_set, cache_delete,invalidate_pattern,
    TTL_VOLATILE,  L1_VOLATILE,
    TTL_MEDIUM,    L1_MEDIUM,
    TTL_PERMANENT, L1_PERMANENT,
)
from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
    UpdateRouteTitleRequest,
)

import logging
logger = logging.getLogger(__name__)

_KEY_ROLES       = "roles:list"
_KEY_EMP_ROLES   = "roles:employees"
_KEY_PERMISSIONS = "roles:route_permissions"


async def invalidate_roles():         await cache_delete(_KEY_ROLES)
async def invalidate_employee_roles(): await cache_delete(_KEY_EMP_ROLES)
async def invalidate_permissions():
    await cache_delete(_KEY_PERMISSIONS)
    await invalidate_pattern("roles:route_permissions:*")


# ── Roles ─────────────────────────────────────────────────────────────────────

async def list_roles():
    cached = await cache_get(_KEY_ROLES, l1_ttl=L1_MEDIUM)
    if cached is not None:
        return cached
    rows       = await db.roles.find_many(order=[{"role_name": "asc"}])
    serialized = [r.model_dump() for r in rows]
    await cache_set(_KEY_ROLES, serialized, ttl=TTL_MEDIUM, l1_ttl=L1_MEDIUM)
    return serialized


async def create_role(
    body: CreateRoleRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    role_code = body.role_code.upper()
    existing  = await db.roles.find_first(where={"role_code": role_code})
    if existing:
        raise HTTPException(status_code=409, detail=f"Role '{role_code}' already exists")

    result = None
    async with audit_ctx(
        user_id    = current_user.id,
        request    = request,
        table_name = "roles",
        record_id  = lambda: str(result.role_id),
        operation  = "INSERT",
        new_values = lambda: result.model_dump(),
    ):
        result = await db.roles.create(data={
            "role_name":   body.role_name,
            "role_code":   role_code,
            "description": body.description,
            "created_by":  current_user.id,
            "updated_by":  current_user.id,
            "updated_at":  datetime.now(timezone.utc),
        })

    await invalidate_roles()
    return result


# ── Employee ↔ Role ───────────────────────────────────────────────────────────

async def list_employee_roles():
    cached = await cache_get(_KEY_EMP_ROLES, l1_ttl=L1_VOLATILE)
    if cached is not None:
        return cached

    records = await db.employee_roles.find_many(
        where={"is_active": True},
        include={
            "employees_employee_roles_employee_idToemployees": True,
            "roles": True,
        },
        order=[{"assigned_at": "desc"}],
    )

    data = [
        {
            "employee_role_id": r.employee_role_id,
            "assigned_at":      r.assigned_at.isoformat() if r.assigned_at else None,
            "is_active":        r.is_active,
            "employee": {
                "id":       r.employees_employee_roles_employee_idToemployees.employee_id,
                "username": r.employees_employee_roles_employee_idToemployees.username,
                "email":    r.employees_employee_roles_employee_idToemployees.email,
            },
            "role": {
                "id":   r.roles.role_id,
                "name": r.roles.role_name,
                "code": r.roles.role_code,
            },
        }
        for r in records
    ]
    await cache_set(_KEY_EMP_ROLES, data, ttl=TTL_VOLATILE, l1_ttl=L1_VOLATILE)
    return data


async def assign_role(
    body: AssignRoleRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    existing = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee already has this role")

    result = None
    async with audit_ctx(
        user_id    = current_user.id,
        request    = request,
        table_name = "employee_roles",
        record_id  = lambda: str(result.employee_role_id),
        operation  = "INSERT",
        new_values = lambda: {
            "employee_id": body.employee_id,
            "role_id":     body.role_id,
            "assigned_by": current_user.id,
        },
    ):
        result = await db.employee_roles.create(data={
            "employee_id": body.employee_id,
            "role_id":     body.role_id,
            "assigned_by": current_user.id,
            "created_by":  current_user.id,
            "updated_by":  current_user.id,
            "updated_at":  datetime.now(timezone.utc),
        })

    await invalidate_employee_roles()
    return result


async def revoke_role(
    body: RevokeRoleRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    record = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active role assignment not found")

    result = None
    async with audit_ctx(
        user_id    = current_user.id,
        request    = request,
        table_name = "employee_roles",
        record_id  = str(record.employee_role_id),
        operation  = "REVOKE",
        old_values = {"is_active": True, "employee_id": body.employee_id, "role_id": body.role_id},
        new_values = lambda: {"is_active": False, "revoked_by": current_user.id},
    ):
        result = await db.employee_roles.update(
            where={"employee_role_id": record.employee_role_id},
            data={
                "is_active":  False,
                "revoked_at": datetime.now(timezone.utc),
                "revoked_by": current_user.id,
                "updated_by": current_user.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )

    await invalidate_employee_roles()
    return result


# ── Route permissions ─────────────────────────────────────────────────────────

async def list_route_permissions():
    cached = await cache_get(_KEY_PERMISSIONS, l1_ttl=L1_PERMANENT)
    if cached is not None:
        return cached

    rows = await db.route_permissions.find_many(
        where={"is_active": True},
        include={"roles": True},
        order=[{"route_key": "asc"}],
    )

    grouped: dict[str, dict] = {}
    for row in rows:
        key = row.route_key
        if key not in grouped:
            grouped[key] = {"route_key": key, "title": row.title, "roles": []}
        elif row.title and not grouped[key]["title"]:
            grouped[key]["title"] = row.title
        grouped[key]["roles"].append({
            "role_id":   row.role_id,
            "role_code": row.roles.role_code,
            "role_name": row.roles.role_name,
        })

    data = list(grouped.values())
    await cache_set(_KEY_PERMISSIONS, data, ttl=TTL_PERMANENT, l1_ttl=L1_PERMANENT)
    return data


async def add_route_permission(
    body: SetRoutePermissionRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    existing = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id}
    )

    result = None
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="Permission already exists and is active")
        async with audit_ctx(
            user_id    = current_user.id,
            request    = request,
            table_name = "route_permissions",
            record_id  = str(existing.id),
            operation  = "INSERT",
            new_values = lambda: {"route_key": body.route_key, "role_id": body.role_id, "is_active": True},
        ):
            result = await db.route_permissions.update(
                where={"id": existing.id},
                data={
                    "is_active":  True,
                    "title":      body.title or existing.title,
                    "updated_by": current_user.id,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
    else:
        async with audit_ctx(
            user_id    = current_user.id,
            request    = request,
            table_name = "route_permissions",
            record_id  = lambda: str(result.id),
            operation  = "INSERT",
            new_values = lambda: {"route_key": body.route_key, "role_id": body.role_id},
        ):
            result = await db.route_permissions.create(data={
                "route_key":  body.route_key,
                "role_id":    body.role_id,
                "title":      body.title,
                "is_active":  True,
                "created_by": current_user.id,
                "updated_by": current_user.id,
                "updated_at": datetime.now(timezone.utc),
            })

    await invalidate_permissions()
    return result

# ── Add this to src/roles/service.py ─────────────────────────────────────────

async def get_my_permissions(current_user: CurrentUser) -> list[str]:
    """
    Returns all route_keys the current user is permitted to access,
    based on their assigned role codes.

    Steps:
    1. Look up the user's active role assignments to get their role_ids.
    2. Find all active route_permissions for those role_ids.
    3. Return the deduplicated list of route_keys.

    This is intentionally lean — no titles, no role metadata. The frontend
    only needs the route_key strings to decide visibility.
    """
    # 1. Get the user's active role assignments
    assignments = await db.employee_roles.find_many(
        where={"employee_id": current_user.id, "is_active": True},
        include={"roles": True},
    )

    if not assignments:
        return []

    role_ids = [a.role_id for a in assignments]

    # 2. Fetch all active permissions for those roles
    permissions = await db.route_permissions.find_many(
        where={"role_id": {"in": role_ids}, "is_active": True},
    )

    # 3. Deduplicate and return just the route_keys
    return list({p.route_key for p in permissions})

async def remove_route_permission(
    body: DeleteRoutePermissionRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    record = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active permission not found")

    result = None
    async with audit_ctx(
        user_id    = current_user.id,
        request    = request,
        table_name = "route_permissions",
        record_id  = str(record.id),
        operation  = "DELETE",
        old_values = {"route_key": body.route_key, "role_id": body.role_id, "is_active": True},
        new_values = lambda: {"is_active": False},
    ):
        result = await db.route_permissions.update(
            where={"id": record.id},
            data={
                "is_active":  False,
                "updated_by": current_user.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )

    await invalidate_permissions()
    return result


async def update_route_title(
    body: UpdateRouteTitleRequest,
    current_user: CurrentUser,
    request: Optional[Request] = None,
):
    rows = await db.route_permissions.find_many(where={"route_key": body.route_key})
    if not rows:
        raise HTTPException(status_code=404, detail="No permissions found for this route_key")

    # Title update is metadata only — one app-level audit row is enough
    from src.common.audit import audit
    await db.route_permissions.update_many(
        where={"route_key": body.route_key},
        data={
            "title":      body.title,
            "updated_by": current_user.id,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await audit(
        table_name   = "route_permissions",
        record_id    = str(rows[0].id),
        operation    = "UPDATE",
        performed_by = current_user.id,
        new_values   = {"route_key": body.route_key, "title": body.title},
        request      = request,
    )

    await invalidate_permissions()
    return {"route_key": body.route_key, "title": body.title, "updated_rows": len(rows)}


async def get_my_permissions(current_user: CurrentUser):
    # Find all active role IDs assigned to currently logged in employee
    user_roles = await db.employee_roles.find_many(
        where={
            "employee_id": current_user.id,
            "is_active": True
        }
    )
    role_ids = [r.role_id for r in user_roles]

    if not role_ids:
        return []

    # Find all unique active route keys for those roles
    permissions = await db.route_permissions.find_many(
        where={
            "role_id": {"in": role_ids},
            "is_active": True
        }
    )

    # Return a unique list of route_keys as expected by the frontend
    return list(set(p.route_key for p in permissions))