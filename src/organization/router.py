# src/organization/router.py

from fastapi import APIRouter, Depends, Query
from typing import Optional
from uuid import UUID
from src.organization import schemas, service
from src.common.dependencies import check_route_permission, CurrentUser

departments_router = APIRouter()
designations_router = APIRouter()
department_types_router = APIRouter()


# ══════════════════════════════════════════════
#  DEPARTMENT ROUTES
# ══════════════════════════════════════════════

@departments_router.get("", response_model=schemas.DepartmentListResponse)
async def list_departments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve paginated list of departments."""
    return await service.list_departments(page, limit, is_active, search)


@departments_router.get("/{department_id}", response_model=schemas.DepartmentDetailResponse)
async def get_department(
    department_id: str,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve detailed department info."""
    return await service.get_department_detail(department_id)


@departments_router.post("", response_model=schemas.DepartmentCreatedResponse, status_code=201)
async def create_department(
    payload: schemas.CreateDepartmentRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create a new department."""
    return await service.create_department(payload, current_user.id)


@departments_router.put("/{department_id}", response_model=schemas.DepartmentUpdatedResponse)
async def update_department(
    department_id: str,
    payload: schemas.UpdateDepartmentRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Update a department."""
    return await service.update_department(department_id, payload, current_user.id)


# ══════════════════════════════════════════════
#  DESIGNATION ROUTES
# ══════════════════════════════════════════════

@designations_router.get("", response_model=schemas.DesignationListResponse)
async def list_designations(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve paginated list of designations."""
    return await service.list_designations(page, limit, is_active)


@designations_router.get("/{designation_id}", response_model=schemas.DesignationDetailResponse)
async def get_designation(
    designation_id: str,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve detailed designation info."""
    return await service.get_designation_detail(designation_id)


@designations_router.post("", response_model=schemas.DesignationListItem, status_code=201)
async def create_designation(
    payload: schemas.CreateDesignationRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create a designation."""
    return await service.create_designation(payload, current_user.id)


@designations_router.put("/{designation_id}", response_model=schemas.DesignationDetailResponse)
async def update_designation(
    designation_id: str,
    payload: schemas.UpdateDesignationRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Update a designation."""
    return await service.update_designation(designation_id, payload, current_user.id)


# ══════════════════════════════════════════════
#  DEPARTMENT TYPES ROUTE (For Dropdowns)
# ══════════════════════════════════════════════

@department_types_router.get("", response_model=list[schemas.DepartmentTypeResponse])
async def get_all_department_types(
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve all department types for frontend dropdowns."""
    return await service.list_department_types()