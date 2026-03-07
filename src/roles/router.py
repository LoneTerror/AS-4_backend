# src/roles/router.py

from fastapi import APIRouter, Depends

from src.common.dependencies import check_route_permission, CurrentUser
from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
)
import src.roles.service as service

router = APIRouter(tags=["Role Management"])


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/v1/roles")
async def list_roles(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_roles()


@router.post("/v1/roles", status_code=201)
async def create_role(
    body: CreateRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.create_role(body, current_user)


# ── Employee ↔ Role ───────────────────────────────────────────────────────────

@router.get("/v1/roles/employees")
async def list_employee_roles(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_employee_roles()


@router.post("/v1/roles/assign", status_code=201)
async def assign_role(
    body: AssignRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.assign_role(body, current_user)


@router.post("/v1/roles/revoke")
async def revoke_role(
    body: RevokeRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.revoke_role(body, current_user)


# ── Route permissions ─────────────────────────────────────────────────────────

@router.get("/v1/route-permissions")
async def list_route_permissions(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_route_permissions()


@router.post("/v1/route-permissions", status_code=201)
async def add_route_permission(
    body: SetRoutePermissionRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.add_route_permission(body, current_user)


@router.patch("/v1/route-permissions")
async def remove_route_permission(
    body: DeleteRoutePermissionRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.remove_route_permission(body, current_user)