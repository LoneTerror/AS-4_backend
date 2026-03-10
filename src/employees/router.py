# src/employees/router.py

from fastapi import APIRouter, Depends, Query
from typing import Optional
from uuid import UUID
from src.employees import schemas, service
from src.common.dependencies import check_route_permission, CurrentUser

router = APIRouter()


@router.get("/list", response_model=schemas.EmployeeListResponse)
async def get_employees(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    department_id: Optional[UUID] = None,
    designation_id: Optional[UUID] = None,
    status_id: Optional[UUID] = None,
    manager_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve paginated list of employees."""
    return await service.list_employees(
        page, limit, department_id, designation_id, status_id, manager_id,
        is_active, search, sort_by, sort_order,
    )


@router.get("/{employee_id}", response_model=schemas.EmployeeDetailResponse)
async def get_employee_by_id(
    employee_id: str,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Retrieve detailed employee info."""
    return await service.get_employee_detail(employee_id)


@router.post("/create", response_model=schemas.EmployeeCreatedResponse, status_code=201)
async def create_employee(
    payload: schemas.CreateEmployeeRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create new employee."""
    return await service.create_employee(payload, current_user.id)


@router.put("/{employee_id}", response_model=schemas.EmployeeDetailResponse)
async def update_employee(
    employee_id: str,
    payload: schemas.UpdateEmployeeRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Update employee."""
    return await service.update_employee(employee_id, payload, current_user.id)


@router.patch("/{employee_id}", status_code=204)
async def patch_employee(
    employee_id: str,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Soft delete employee."""
    await service.patch_employee(employee_id, current_user.id)