from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Optional
from uuid import UUID

# Corrected imports pointing to the new src.organization folder
from src.organization import schemas
from src.organization import service
from src.organization.dependencies import get_current_employee, CurrentEmployee

departments_router = APIRouter()
designations_router = APIRouter()
department_types_router = APIRouter()  # Added the missing router for dropdowns


def require_roles(current_emp: CurrentEmployee, allowed_roles: list[str]):
    user_roles = [r.upper() for r in current_emp.roles]
    if not any(role in user_roles for role in allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required: {allowed_roles}"
        )


# ══════════════════════════════════════════════
#  DEPARTMENT ROUTES
# ══════════════════════════════════════════════

@departments_router.get("", response_model=schemas.DepartmentListResponse)
async def list_departments(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve paginated list of departments."""
    require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
    return await service.list_departments(page, limit, is_active, search)


@departments_router.get("/{department_id}", response_model=schemas.DepartmentDetailResponse)
async def get_department(
    department_id: str,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve detailed department info."""
    require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
    return await service.get_department_detail(department_id)


@departments_router.post("", response_model=schemas.DepartmentCreatedResponse, status_code=201)
async def create_department(
    payload: schemas.CreateDepartmentRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Create a new department. HR_ADMIN / SUPER_ADMIN only."""
    require_roles(current_emp, ["HR_ADMIN", "SUPER_ADMIN"])
    return await service.create_department(payload, current_emp.id)


@departments_router.put("/{department_id}", response_model=schemas.DepartmentUpdatedResponse)
async def update_department(
    department_id: str,
    payload: schemas.UpdateDepartmentRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Update a department. HR_ADMIN / SUPER_ADMIN only."""
    require_roles(current_emp, ["HR_ADMIN", "SUPER_ADMIN"])
    return await service.update_department(department_id, payload, current_emp.id)


# ══════════════════════════════════════════════
#  DESIGNATION ROUTES
# ══════════════════════════════════════════════

@designations_router.get("", response_model=schemas.DesignationListResponse)
async def list_designations(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    is_active: Optional[bool] = None,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve paginated list of designations."""
    require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
    return await service.list_designations(page, limit, is_active)


@designations_router.get("/{designation_id}", response_model=schemas.DesignationDetailResponse)
async def get_designation(
    designation_id: str,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve detailed designation info."""
    require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
    return await service.get_designation_detail(designation_id)


@designations_router.post("", response_model=schemas.DesignationListItem, status_code=201)
async def create_designation(
    payload: schemas.CreateDesignationRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Create a designation. HR_ADMIN / SUPER_ADMIN only."""
    require_roles(current_emp, ["HR_ADMIN", "SUPER_ADMIN"])
    return await service.create_designation(payload, current_emp.id)


@designations_router.put("/{designation_id}", response_model=schemas.DesignationDetailResponse)
async def update_designation(
    designation_id: str,
    payload: schemas.UpdateDesignationRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Update a designation. HR_ADMIN / SUPER_ADMIN only."""
    require_roles(current_emp, ["HR_ADMIN", "SUPER_ADMIN"])
    return await service.update_designation(designation_id, payload, current_emp.id)


# ══════════════════════════════════════════════
#  DEPARTMENT TYPES ROUTE (For Dropdowns)
# ══════════════════════════════════════════════

@department_types_router.get("", response_model=list[schemas.DepartmentTypeResponse])
async def get_all_department_types(current_emp: CurrentEmployee = Depends(get_current_employee)):
    """Retrieve all department types for frontend dropdowns."""
    require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
    return await service.list_department_types()