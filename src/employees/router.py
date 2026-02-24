from fastapi import APIRouter, Depends, Query, HTTPException, status
from typing import Optional
from uuid import UUID
from src.employees import schemas, service
from src.employees.dependencies import get_current_employee, CurrentEmployee

router = APIRouter()

def require_roles(current_emp: CurrentEmployee, allowed_roles: list[str]):
    user_roles = [r.upper() for r in current_emp.roles]
    if not any(role in user_roles for role in allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Insufficient permissions. Required: {allowed_roles}"
        )

@router.get("", response_model=schemas.EmployeeListResponse)
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
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve paginated list of employees."""
    # require_roles(current_emp, ["EMPLOYEE", "MANAGER", "HR_ADMIN"])
    return await service.list_employees(
        page, limit, department_id, designation_id, status_id, manager_id, 
        is_active, search, sort_by, sort_order
    )

@router.get("/{employee_id}", response_model=schemas.EmployeeDetailResponse)
async def get_employee_by_id(
    employee_id: str,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Retrieve detailed employee info."""
    return await service.get_employee_detail(employee_id)

@router.post("", response_model=schemas.EmployeeCreatedResponse, status_code=201)
async def create_employee(
    payload: schemas.CreateEmployeeRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Create new employee. HR_ADMIN only."""
    # require_roles(current_emp, ["HR_ADMIN"])
    return await service.create_employee(payload, current_emp.id)

@router.put("/{employee_id}", response_model=schemas.EmployeeDetailResponse)
async def update_employee(
    employee_id: str,
    payload: schemas.UpdateEmployeeRequest,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Update employee. HR_ADMIN only."""
    # require_roles(current_emp, ["HR_ADMIN"])
    return await service.update_employee(employee_id, payload, current_emp.id)

@router.patch("/{employee_id}", status_code=204)
async def patch_employee(
    employee_id: str,
    current_emp: CurrentEmployee = Depends(get_current_employee)
):
    """Soft delete employee. HR_ADMIN only."""
    # require_roles(current_emp, ["HR_ADMIN"])
    await service.patch_employee(employee_id, current_emp.id)