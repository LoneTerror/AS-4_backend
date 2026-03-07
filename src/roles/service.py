# src/roles/service.py

from datetime import datetime, timezone
from fastapi import HTTPException

from src.prisma.client import db
from src.common.dependencies import CurrentUser
from src.common.cache import cache_get, cache_set, cache_delete, invalidate_pattern
from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
)

# ── Cache keys & TTLs ─────────────────────────────────────────────────────────
_KEY_ROLES       = "roles:list"
_KEY_EMP_ROLES   = "roles:employees"
_KEY_PERMISSIONS = "roles:route_permissions"

TTL_ROLES       = 3600  # 1 hr  — almost static
TTL_EMP_ROLES   = 120   # 2 min — changes on assign/revoke
TTL_PERMISSIONS = 3600  # 1 hr  — almost static

async def invalidate_roles():          await cache_delete(_KEY_ROLES)
async def invalidate_employee_roles(): await cache_delete(_KEY_EMP_ROLES)
async def invalidate_permissions():    await cache_delete(_KEY_PERMISSIONS)
# ─────────────────────────────────────────────────────────────────────────────


async def list_roles():
    cached = await cache_get(_KEY_ROLES)
    if cached is not None:
        return cached

    rows = await db.roles.find_many(order=[{"role_name": "asc"}])
    await cache_set(_KEY_ROLES, [r.model_dump() for r in rows], ttl=TTL_ROLES)
    return rows


async def create_role(body: CreateRoleRequest, current_user: CurrentUser):
    existing = await db.roles.find_first(where={"role_code": body.role_code.upper()})
    if existing:
        raise HTTPException(status_code=409, detail=f"Role '{body.role_code}' already exists")

    result = await db.roles.create(data={
        "role_name":   body.role_name,
        "role_code":   body.role_code.upper(),
        "description": body.description,
        "created_by":  current_user.id,
        "updated_by":  current_user.id,
        "updated_at":  datetime.now(timezone.utc),
    })
    await invalidate_roles()
    return result


async def list_employee_roles():
    cached = await cache_get(_KEY_EMP_ROLES)
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
    await cache_set(_KEY_EMP_ROLES, data, ttl=TTL_EMP_ROLES)
    return data


async def assign_role(body: AssignRoleRequest, current_user: CurrentUser):
    existing = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee already has this role")

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


async def revoke_role(body: RevokeRoleRequest, current_user: CurrentUser):
    record = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active role assignment not found")

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


async def list_route_permissions():
    cached = await cache_get(_KEY_PERMISSIONS)
    if cached is not None:
        return cached

    rows = await db.route_permissions.find_many(
        where={"is_active": True},
        include={"roles": True},
        order=[{"route_key": "asc"}],
    )
    grouped: dict = {}
    for row in rows:
        key = row.route_key
        if key not in grouped:
            grouped[key] = {"route_key": key, "roles": []}
        grouped[key]["roles"].append({
            "role_id":   row.role_id,
            "role_code": row.roles.role_code,
            "role_name": row.roles.role_name,
        })
    data = list(grouped.values())
    await cache_set(_KEY_PERMISSIONS, data, ttl=TTL_PERMISSIONS)
    return data


async def add_route_permission(body: SetRoutePermissionRequest, current_user: CurrentUser):
    existing = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id}
    )
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="Permission already exists")
        result = await db.route_permissions.update(
            where={"id": existing.id},
            data={
                "is_active":  True,
                "updated_by": current_user.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )
    else:
        result = await db.route_permissions.create(data={
            "route_key":  body.route_key,
            "role_id":    body.role_id,
            "is_active":  True,
            "created_by": current_user.id,
            "updated_by": current_user.id,
            "updated_at": datetime.now(timezone.utc),
        })

    await invalidate_permissions()
    return result


async def remove_route_permission(body: DeleteRoutePermissionRequest, current_user: CurrentUser):
    record = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active permission not found")

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