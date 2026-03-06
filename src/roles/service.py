# src/roles/service.py

from datetime import datetime, timezone
from fastapi import HTTPException

from src.prisma.client import db
from src.common.dependencies import CurrentUser
from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
)


async def list_roles():
    return await db.roles.find_many(
        order=[{"role_name": "asc"}],
    )


async def create_role(body: CreateRoleRequest, current_user: CurrentUser):
    existing = await db.roles.find_first(where={"role_code": body.role_code.upper()})
    if existing:
        raise HTTPException(status_code=409, detail=f"Role '{body.role_code}' already exists")

    return await db.roles.create(data={
        "role_name":   body.role_name,
        "role_code":   body.role_code.upper(),
        "description": body.description,
        "created_by":  current_user.id,
        "updated_by":  current_user.id,
        "updated_at":  datetime.now(timezone.utc),
    })


async def list_employee_roles():
    records = await db.employee_roles.find_many(
        where={"is_active": True},
        include={
            "employees_employee_roles_employee_idToemployees": True,
            "roles": True,
        },
        order=[{"assigned_at": "desc"}],
    )

    return [
        {
            "employee_role_id": r.employee_role_id,
            "assigned_at":      r.assigned_at,
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


async def assign_role(body: AssignRoleRequest, current_user: CurrentUser):
    existing = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if existing:
        raise HTTPException(status_code=409, detail="Employee already has this role")

    return await db.employee_roles.create(data={
        "employee_id": body.employee_id,
        "role_id":     body.role_id,
        "assigned_by": current_user.id,
        "created_by":  current_user.id,
        "updated_by":  current_user.id,
        "updated_at":  datetime.now(timezone.utc),
    })


async def revoke_role(body: RevokeRoleRequest, current_user: CurrentUser):
    record = await db.employee_roles.find_first(
        where={"employee_id": body.employee_id, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active role assignment not found")

    return await db.employee_roles.update(
        where={"employee_role_id": record.employee_role_id},
        data={
            "is_active":  False,
            "revoked_at": datetime.now(timezone.utc),
            "revoked_by": current_user.id,
            "updated_by": current_user.id,
            "updated_at": datetime.now(timezone.utc),
        },
    )


async def list_route_permissions():
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
    return list(grouped.values())


async def add_route_permission(body: SetRoutePermissionRequest, current_user: CurrentUser):
    existing = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id}
    )
    if existing:
        if existing.is_active:
            raise HTTPException(status_code=409, detail="Permission already exists")
        # Reactivate a previously revoked permission instead of creating a duplicate
        return await db.route_permissions.update(
            where={"id": existing.id},
            data={
                "is_active":  True,
                "updated_by": current_user.id,
                "updated_at": datetime.now(timezone.utc),
            },
        )

    return await db.route_permissions.create(data={
        "route_key":  body.route_key,
        "role_id":    body.role_id,
        "is_active":  True,
        "created_by": current_user.id,
        "updated_by": current_user.id,
        "updated_at": datetime.now(timezone.utc),
    })


async def remove_route_permission(body: DeleteRoutePermissionRequest, current_user: CurrentUser):
    record = await db.route_permissions.find_first(
        where={"route_key": body.route_key, "role_id": body.role_id, "is_active": True}
    )
    if not record:
        raise HTTPException(status_code=404, detail="Active permission not found")

    return await db.route_permissions.update(
        where={"id": record.id},
        data={
            "is_active":  False,
            "updated_by": current_user.id,
            "updated_at": datetime.now(timezone.utc),
        },
    )