# src/roles/router.py

from fastapi import APIRouter, Depends

from src.common.dependencies import check_route_permission, CurrentUser
from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
    UpdateRouteTitleRequest,
)
import src.roles.service as service

router = APIRouter(tags=["Role Management"])


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/list")
async def list_roles(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_roles()


@router.post("/create", status_code=201)
async def create_role(
    body: CreateRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.create_role(body, current_user)


# ── Employee ↔ Role ───────────────────────────────────────────────────────────

@router.get("/employees")
async def list_employee_roles(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_employee_roles()


@router.post("/assign", status_code=201)
async def assign_role(
    body: AssignRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.assign_role(body, current_user)


@router.post("/revoke")
async def revoke_role(
    body: RevokeRoleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.revoke_role(body, current_user)


# ── Route permissions ─────────────────────────────────────────────────────────

@router.get("/route-permissions")
async def list_route_permissions(
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.list_route_permissions()


@router.post("/route-permissions", status_code=201)
async def add_route_permission(
    body: SetRoutePermissionRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.add_route_permission(body, current_user)


@router.patch("/route-permissions")
async def remove_route_permission(
    body: DeleteRoutePermissionRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    return await service.remove_route_permission(body, current_user)


@router.patch("/route-permissions/title")
async def update_route_title(
    body: UpdateRouteTitleRequest,
    current_user: CurrentUser = Depends(check_route_permission)
):
    """Set or update the human-readable display title for a route key."""
    return await service.update_route_title(body, current_user)