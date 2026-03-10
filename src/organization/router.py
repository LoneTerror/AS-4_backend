# src/organization/router.py

from fastapi import APIRouter, Depends, Query, Response
from typing import Optional
from uuid import UUID
from datetime import datetime
from src.organization import schemas, service
from src.common.dependencies import check_route_permission, CurrentUser

departments_router = APIRouter()
designations_router = APIRouter()
department_types_router = APIRouter()
statuses_router = APIRouter()
audit_logs_router = APIRouter()
seasonal_multipliers_router = APIRouter()


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

# ══════════════════════════════════════════════
#  5.5 STATUS MASTER ROUTES
# ══════════════════════════════════════════════

@statuses_router.get("", response_model=list[schemas.StatusResponse])
async def list_statuses(
    entity_type: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Returns all status entries, optionally filtered by entity_type."""
    return await service.list_statuses(entity_type)


@statuses_router.get("/{status_id}", response_model=schemas.StatusDetailResponse)
async def get_status(status_id: str, current_user: CurrentUser = Depends(check_route_permission)):
    """Full detail of a single status entry."""
    return await service.get_status(status_id)


@statuses_router.post("", response_model=schemas.StatusDetailResponse, status_code=201)
async def create_status(
    payload: schemas.CreateStatusRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Creates a new status code. SUPER_ADMIN only."""
    return await service.create_status(payload, current_user.id)


@statuses_router.put("/{status_id}", response_model=schemas.StatusDetailResponse)
async def update_status(
    status_id: str,
    payload: schemas.UpdateStatusRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Updates status name or description. SUPER_ADMIN only."""
    return await service.update_status(status_id, payload, current_user.id)


# ══════════════════════════════════════════════
#  5.6 AUDIT LOGS ROUTES
# ══════════════════════════════════════════════

@audit_logs_router.get("", response_model=dict)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    table_name: Optional[str] = None,
    record_id: Optional[str] = None,
    operation_type: Optional[str] = None,
    performed_by: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Paginated audit log viewer with filters. SUPER_ADMIN only."""
    return await service.list_audit_logs(
        page, limit, table_name, record_id, operation_type, performed_by, start_date, end_date
    )


@audit_logs_router.get("/{audit_id}", response_model=schemas.AuditLogResponse)
async def get_audit_log(audit_id: str, current_user: CurrentUser = Depends(check_route_permission)):
    """Returns full detail of a single audit log entry. SUPER_ADMIN only."""
    return await service.get_audit_log(audit_id)


# ══════════════════════════════════════════════
#  5.7 SEASONAL MULTIPLIERS ROUTES
# ══════════════════════════════════════════════

@seasonal_multipliers_router.get("/active", response_model=schemas.SeasonalMultiplierResponse)
async def get_active_multiplier(current_user: CurrentUser = Depends(check_route_permission)):
    """Returns the single currently active seasonal multiplier."""
    return await service.get_active_seasonal_multiplier()


@seasonal_multipliers_router.get("", response_model=list[schemas.SeasonalMultiplierResponse])
async def list_seasonal_multipliers(
    quarter: Optional[int] = Query(None, ge=1, le=4),
    active_only: bool = Query(False),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Returns all seasonal multipliers ordered by quarter and effective_from."""
    return await service.list_seasonal_multipliers(quarter, active_only)


@seasonal_multipliers_router.post("", response_model=schemas.SeasonalMultiplierResponse, status_code=201)
async def create_seasonal_multiplier(
    payload: schemas.CreateSeasonalMultiplierRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Creates a new seasonal multiplier. SUPER_ADMIN only."""
    return await service.create_seasonal_multiplier(payload, current_user.id)


@seasonal_multipliers_router.put("/{mult_id}", response_model=schemas.SeasonalMultiplierResponse)
async def update_seasonal_multiplier(
    mult_id: str,
    payload: schemas.UpdateSeasonalMultiplierRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Updates a seasonal multiplier. SUPER_ADMIN only."""
    return await service.update_seasonal_multiplier(mult_id, payload, current_user.id)


@seasonal_multipliers_router.patch("/{mult_id}", status_code=204)
async def patch_seasonal_multiplier(
    mult_id: str,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Deletes a future seasonal multiplier only. SUPER_ADMIN only."""
    await service.patch_seasonal_multiplier(mult_id)
    return Response(status_code=204)