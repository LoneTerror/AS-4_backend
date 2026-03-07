import math
from typing import Optional
from uuid import UUID
from datetime import datetime, date
from fastapi import HTTPException
from src.prisma.client import db

from src.organization import schemas


# ══════════════════════════════════════════════
#  DEPARTMENT SERVICE
# ══════════════════════════════════════════════

async def list_departments(
    page: int,
    limit: int,
    is_active: Optional[bool],
    search: Optional[str]
) -> schemas.DepartmentListResponse:

    where: dict = {}
    and_conditions = []

    if search:
        and_conditions.append({
            "OR": [
                {"department_name": {"contains": search, "mode": "insensitive"}},
                {"department_code": {"contains": search, "mode": "insensitive"}}
            ]
        })

    if and_conditions:
        where["AND"] = and_conditions

    total = await db.departments.count(where=where)
    total_pages = math.ceil(total / limit) if total else 1
    skip = (page - 1) * limit

    departments = await db.departments.find_many(
        where=where,
        skip=skip,
        take=limit,
        order={"created_at": "desc"},
        include={"department_types": True}
    )

    data = []
    for dept in departments:
        dept_type = None
        if dept.department_types:
            dept_type = schemas.DepartmentTypeResponse(
                department_type_id=dept.department_types.department_type_id,
                type_name=dept.department_types.type_name,
                type_code=dept.department_types.type_code
            )

        data.append(schemas.DepartmentListItem(
            department_id=dept.department_id,
            department_name=dept.department_name,
            department_code=dept.department_code,
            department_type=dept_type,
            manager=None,  # No manager_id column on departments table
            is_active=True,  # No is_active column on departments; default True
            created_at=dept.created_at
        ))

    return schemas.DepartmentListResponse(
        data=data,
        pagination=schemas.PaginationMeta(
            current_page=page,
            per_page=limit,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1
        )
    )


async def get_department_detail(department_id: str) -> schemas.DepartmentDetailResponse:
    dept = await db.departments.find_unique(
        where={"department_id": department_id},
        include={
            "department_types": True,
            "employees_employees_department_idTodepartments": True
        }
    )

    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    dept_type = None
    if dept.department_types:
        dept_type = schemas.DepartmentTypeResponse(
            department_type_id=dept.department_types.department_type_id,
            type_name=dept.department_types.type_name,
            type_code=dept.department_types.type_code
        )

    emp_list = dept.employees_employees_department_idTodepartments or []
    employee_count = len(emp_list)

    return schemas.DepartmentDetailResponse(
        department_id=dept.department_id,
        department_name=dept.department_name,
        department_code=dept.department_code,
        department_type=dept_type,
        manager=None,
        employee_count=employee_count,
        is_active=True,
        created_at=dept.created_at,
        updated_at=dept.updated_at
    )


async def create_department(
    data: schemas.CreateDepartmentRequest,
    created_by_id: str
) -> schemas.DepartmentCreatedResponse:
    # Uniqueness checks
    existing = await db.departments.find_first(
        where={
            "OR": [
                {"department_name": data.department_name},
                {"department_code": data.department_code}
            ]
        }
    )
    if existing:
        raise HTTPException(status_code=400, detail="Department name or code already exists")

    # Validate type exists
    dept_type = await db.department_types.find_unique(
        where={"department_type_id": str(data.department_type_id)}
    )
    if not dept_type:
        raise HTTPException(status_code=400, detail="Department type not found")

    now = datetime.now()
    new_dept = await db.departments.create(
        data={
            "department_name": data.department_name,
            "department_code": data.department_code,
            "department_type_id": str(data.department_type_id),
            "created_by": created_by_id,
            "updated_by": created_by_id,
            "updated_at": now
        },
        include={"department_types": True}
    )

    dept_type_resp = None
    if new_dept.department_types:
        dept_type_resp = schemas.DepartmentTypeResponse(
            department_type_id=new_dept.department_types.department_type_id,
            type_name=new_dept.department_types.type_name,
            type_code=new_dept.department_types.type_code
        )

    return schemas.DepartmentCreatedResponse(
        department_id=new_dept.department_id,
        department_name=new_dept.department_name,
        department_code=new_dept.department_code,
        department_type=dept_type_resp,
        manager=None,
        is_active=True,
        created_at=new_dept.created_at,
        created_by=new_dept.created_by
    )


async def update_department(
    department_id: str,
    data: schemas.UpdateDepartmentRequest,
    updated_by_id: str
) -> schemas.DepartmentUpdatedResponse:
    existing = await db.departments.find_unique(where={"department_id": department_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Department not found")

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()
                   if k not in ("is_active",)}  # is_active not in schema

    if "department_type_id" in update_data and update_data["department_type_id"]:
        update_data["department_type_id"] = str(update_data["department_type_id"])

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = await db.departments.update(
        where={"department_id": department_id},
        data=update_data,
        include={"department_types": True}
    )

    dept_type_resp = None
    if updated.department_types:
        dept_type_resp = schemas.DepartmentTypeResponse(
            department_type_id=updated.department_types.department_type_id,
            type_name=updated.department_types.type_name,
            type_code=updated.department_types.type_code
        )

    return schemas.DepartmentUpdatedResponse(
        department_id=updated.department_id,
        department_name=updated.department_name,
        department_code=updated.department_code,
        department_type=dept_type_resp,
        manager=None,
        is_active=True,
        updated_at=updated.updated_at,
        updated_by=updated.updated_by
    )


async def list_department_types() -> list[schemas.DepartmentTypeResponse]:
    """
    Returns all department types as schema objects (not raw Prisma models).
    Previously returned raw Prisma objects which would fail Pydantic serialization.
    """
    types = await db.department_types.find_many(order={"type_name": "asc"})
    return [
        schemas.DepartmentTypeResponse(
            department_type_id=t.department_type_id,
            type_name=t.type_name,
            type_code=t.type_code
        )
        for t in types
    ]


# ══════════════════════════════════════════════
#  DESIGNATION SERVICE
# ══════════════════════════════════════════════

async def list_designations(
    page: int,
    limit: int,
    is_active: Optional[bool]
) -> schemas.DesignationListResponse:

    # designations has no is_active column in schema — ignore filter
    total = await db.designations.count()
    total_pages = math.ceil(total / limit) if total else 1
    skip = (page - 1) * limit

    designations = await db.designations.find_many(
        skip=skip,
        take=limit,
        order={"level": "asc"}
    )

    data = [
        schemas.DesignationListItem(
            designation_id=d.designation_id,
            designation_name=d.designation_name,
            designation_code=d.designation_code,
            level=d.level,
            is_active=True,  # No is_active column in schema
            created_at=d.created_at
        )
        for d in designations
    ]

    return schemas.DesignationListResponse(
        data=data,
        pagination=schemas.PaginationMeta(
            current_page=page,
            per_page=limit,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1
        )
    )


async def get_designation_detail(designation_id: str) -> schemas.DesignationDetailResponse:
    desig = await db.designations.find_unique(
        where={"designation_id": designation_id},
        include={"employees_employees_designation_idTodesignations": True}
    )

    if not desig:
        raise HTTPException(status_code=404, detail="Designation not found")

    emp_list = desig.employees_employees_designation_idTodesignations or []

    return schemas.DesignationDetailResponse(
        designation_id=desig.designation_id,
        designation_name=desig.designation_name,
        designation_code=desig.designation_code,
        level=desig.level,
        description=None,  # No description column in schema
        employee_count=len(emp_list),
        is_active=True,
        created_at=desig.created_at,
        updated_at=desig.updated_at
    )


async def create_designation(
    data: schemas.CreateDesignationRequest,
    created_by_id: str
) -> schemas.DesignationListItem:
    existing = await db.designations.find_first(
        where={
            "OR": [
                {"designation_name": data.designation_name},
                {"designation_code": data.designation_code}
            ]
        }
    )
    if existing:
        raise HTTPException(status_code=400, detail="Designation name or code already exists")

    now = datetime.now()
    new_desig = await db.designations.create(
        data={
            "designation_name": data.designation_name,
            "designation_code": data.designation_code,
            "level": data.level,
            "created_by": created_by_id,
            "updated_by": created_by_id,
            "updated_at": now
        }
    )

    return schemas.DesignationListItem(
        designation_id=new_desig.designation_id,
        designation_name=new_desig.designation_name,
        designation_code=new_desig.designation_code,
        level=new_desig.level,
        is_active=True,
        created_at=new_desig.created_at
    )


async def update_designation(
    designation_id: str,
    data: schemas.UpdateDesignationRequest,
    updated_by_id: str
) -> schemas.DesignationDetailResponse:
    existing = await db.designations.find_unique(where={"designation_id": designation_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Designation not found")

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()
                   if k not in ("is_active", "description")}  # not in schema

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    await db.designations.update(
        where={"designation_id": designation_id},
        data=update_data
    )

    return await get_designation_detail(designation_id)

# ══════════════════════════════════════════════
#  5.4 ROLES SERVICE
# ══════════════════════════════════════════════

async def list_roles() -> list[schemas.RoleResponse]:
    roles = await db.roles.find_many(order={"role_name": "asc"})
    return [
        schemas.RoleResponse(
            role_id=r.role_id,
            role_name=r.role_name,
            role_code=r.role_code,
            description=r.description,
            reviewer_weight=r.reviewer_weight,
            created_at=r.created_at,
        )
        for r in roles
    ]


async def get_role(role_id: str) -> schemas.RoleDetailResponse:
    role = await db.roles.find_unique(where={"role_id": role_id})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return schemas.RoleDetailResponse(
        role_id=role.role_id,
        role_name=role.role_name,
        role_code=role.role_code,
        description=role.description,
        reviewer_weight=role.reviewer_weight,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


async def create_role(data: schemas.CreateRoleRequest, created_by_id: str) -> schemas.RoleDetailResponse:
    existing = await db.roles.find_first(
        where={"OR": [{"role_name": data.role_name}, {"role_code": data.role_code}]}
    )
    if existing:
        raise HTTPException(status_code=409, detail="CONFLICT – role_code or role_name already exists")

    now = datetime.now()
    new_role = await db.roles.create(
        data={
            "role_name": data.role_name,
            "role_code": data.role_code,
            "description": data.description,
            "reviewer_weight": str(data.reviewer_weight) if data.reviewer_weight else "1.0000",
            "created_by": created_by_id,
            "updated_by": created_by_id,
            "updated_at": now,
        }
    )
    return schemas.RoleDetailResponse(
        role_id=new_role.role_id,
        role_name=new_role.role_name,
        role_code=new_role.role_code,
        description=new_role.description,
        reviewer_weight=new_role.reviewer_weight,
        created_at=new_role.created_at,
        updated_at=new_role.updated_at,
    )


async def update_role(role_id: str, data: schemas.UpdateRoleRequest, updated_by_id: str) -> schemas.RoleDetailResponse:
    existing = await db.roles.find_unique(where={"role_id": role_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if "reviewer_weight" in update_data:
        update_data["reviewer_weight"] = str(update_data["reviewer_weight"])
    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = await db.roles.update(where={"role_id": role_id}, data=update_data)
    return schemas.RoleDetailResponse(
        role_id=updated.role_id,
        role_name=updated.role_name,
        role_code=updated.role_code,
        description=updated.description,
        reviewer_weight=updated.reviewer_weight,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


async def assign_role(role_id: str, data: schemas.AssignRoleRequest, assigned_by_id: str) -> schemas.AssignRoleResponse:
    role = await db.roles.find_unique(where={"role_id": role_id})
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    emp = await db.employees.find_unique(where={"employee_id": str(data.employee_id)})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    existing = await db.employee_roles.find_first(
        where={"employee_id": str(data.employee_id), "role_id": role_id, "is_active": True}
    )
    if existing:
        raise HTTPException(status_code=409, detail="CONFLICT – Employee already has this role")

    now = datetime.now()
    new_er = await db.employee_roles.create(
        data={
            "employee_id": str(data.employee_id),
            "role_id": role_id,
            "assigned_by": assigned_by_id,
            "created_by": assigned_by_id,
            "updated_by": assigned_by_id,
            "updated_at": now,
        }
    )
    return schemas.AssignRoleResponse(
        employee_role_id=new_er.employee_role_id,
        employee_id=new_er.employee_id,
        role_id=new_er.role_id,
        role_code=role.role_code,
        assigned_at=new_er.assigned_at,
        assigned_by=new_er.assigned_by,
        is_active=new_er.is_active,
    )


async def revoke_role(role_id: str, employee_id: str, revoked_by_id: str) -> schemas.RevokeRoleResponse:
    er = await db.employee_roles.find_first(
        where={"employee_id": employee_id, "role_id": role_id, "is_active": True}
    )
    if not er:
        raise HTTPException(status_code=404, detail="Active role assignment not found")

    now = datetime.now()
    await db.employee_roles.update(
        where={"employee_role_id": er.employee_role_id},
        data={"is_active": False, "revoked_at": now, "revoked_by": revoked_by_id, "updated_by": revoked_by_id, "updated_at": now},
    )
    return schemas.RevokeRoleResponse(
        message="Role revoked successfully.",
        employee_id=UUID(employee_id),
        role_id=UUID(role_id),
        revoked_at=now,
    )


# ══════════════════════════════════════════════
#  5.5 STATUS MASTER SERVICE
# ══════════════════════════════════════════════

async def list_statuses(entity_type: Optional[str] = None) -> list[schemas.StatusResponse]:
    where = {}
    if entity_type:
        where["entity_type"] = entity_type.upper()
    statuses = await db.status_master.find_many(where=where, order={"entity_type": "asc"})
    return [
        schemas.StatusResponse(
            status_id=st.status_id,
            status_code=st.status_code,
            status_name=st.status_name,
            description=st.description,
            entity_type=st.entity_type,
            created_at=st.created_at,
        )
        for st in statuses
    ]


async def get_status(status_id: str) -> schemas.StatusDetailResponse:
    st = await db.status_master.find_unique(where={"status_id": status_id})
    if not st:
        raise HTTPException(status_code=404, detail="Status not found")
    return schemas.StatusDetailResponse(
        status_id=st.status_id,
        status_code=st.status_code,
        status_name=st.status_name,
        description=st.description,
        entity_type=st.entity_type,
        created_at=st.created_at,
        updated_at=st.updated_at,
    )


async def create_status(data: schemas.CreateStatusRequest, created_by_id: str) -> schemas.StatusDetailResponse:
    existing = await db.status_master.find_unique(where={"status_code": data.status_code})
    if existing:
        raise HTTPException(status_code=409, detail="CONFLICT – status_code already exists")

    now = datetime.now()
    new_st = await db.status_master.create(
        data={
            "status_code": data.status_code,
            "status_name": data.status_name,
            "description": data.description,
            "entity_type": data.entity_type,
            "created_by": created_by_id,
            "updated_by": created_by_id,
            "updated_at": now,
        }
    )
    return schemas.StatusDetailResponse(
        status_id=new_st.status_id,
        status_code=new_st.status_code,
        status_name=new_st.status_name,
        description=new_st.description,
        entity_type=new_st.entity_type,
        created_at=new_st.created_at,
        updated_at=new_st.updated_at,
    )


async def update_status(status_id: str, data: schemas.UpdateStatusRequest, updated_by_id: str) -> schemas.StatusDetailResponse:
    existing = await db.status_master.find_unique(where={"status_id": status_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Status not found")

    update_data = data.model_dump(exclude_unset=True)
    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = await db.status_master.update(where={"status_id": status_id}, data=update_data)
    return schemas.StatusDetailResponse(
        status_id=updated.status_id,
        status_code=updated.status_code,
        status_name=updated.status_name,
        description=updated.description,
        entity_type=updated.entity_type,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


# ══════════════════════════════════════════════
#  5.6 AUDIT LOGS SERVICE
# ══════════════════════════════════════════════

async def list_audit_logs(
    page: int,
    limit: int,
    table_name: Optional[str],
    record_id: Optional[str],
    operation_type: Optional[str],
    performed_by: Optional[str],
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> dict:
    where: dict = {}
    if table_name:
        where["table_name"] = table_name
    if record_id:
        where["record_id"] = record_id
    if operation_type:
        where["operation_type"] = operation_type.upper()
    if performed_by:
        where["performed_by"] = performed_by
    if start_date or end_date:
        where["performed_at"] = {}
        if start_date:
            where["performed_at"]["gte"] = start_date
        if end_date:
            where["performed_at"]["lte"] = end_date

    total = await db.audit_log.count(where=where)
    total_pages = math.ceil(total / limit) if total else 1
    skip = (page - 1) * limit

    logs = await db.audit_log.find_many(
        where=where, skip=skip, take=limit, order={"performed_at": "desc"}
    )

    data = [
        schemas.AuditLogResponse(
            audit_id=log.audit_id,
            table_name=log.table_name,
            record_id=log.record_id,
            operation_type=log.operation_type,
            old_values=log.old_values,
            new_values=log.new_values,
            performed_by=log.performed_by,
            performed_at=log.performed_at,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
        )
        for log in logs
    ]

    return {
        "data": data,
        "pagination": schemas.PaginationMeta(
            current_page=page,
            per_page=limit,
            total=total,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    }


async def get_audit_log(audit_id: str) -> schemas.AuditLogResponse:
    log = await db.audit_log.find_unique(where={"audit_id": audit_id})
    if not log:
        raise HTTPException(status_code=404, detail="Audit log entry not found.")
    return schemas.AuditLogResponse(
        audit_id=log.audit_id,
        table_name=log.table_name,
        record_id=log.record_id,
        operation_type=log.operation_type,
        old_values=log.old_values,
        new_values=log.new_values,
        performed_by=log.performed_by,
        performed_at=log.performed_at,
        ip_address=log.ip_address,
        user_agent=log.user_agent,
    )


# ══════════════════════════════════════════════
#  5.7 SEASONAL MULTIPLIERS SERVICE
# ══════════════════════════════════════════════

def _to_mult_response(m) -> schemas.SeasonalMultiplierResponse:
    return schemas.SeasonalMultiplierResponse(
        seasonal_multiplier_id=m.seasonal_multiplier_id,
        quarter=m.quarter,
        label=m.label,
        multiplier=m.multiplier,
        effective_from=m.effective_from,
        effective_to=m.effective_to,
        created_at=m.created_at,
    )


async def list_seasonal_multipliers(
    quarter: Optional[int] = None,
    active_only: bool = False,
) -> list[schemas.SeasonalMultiplierResponse]:
    where: dict = {}
    if quarter:
        where["quarter"] = quarter
    if active_only:
        today = date.today()
        where["effective_from"] = {"lte": today}
        where["effective_to"] = {"gte": today}

    mults = await db.seasonal_multipliers.find_many(
        where=where,
        order=[{"quarter": "asc"}, {"effective_from": "asc"}],
    )
    return [_to_mult_response(m) for m in mults]


async def get_active_seasonal_multiplier() -> schemas.SeasonalMultiplierResponse:
    today = date.today()
    m = await db.seasonal_multipliers.find_first(
        where={"effective_from": {"lte": today}, "effective_to": {"gte": today}},
        order={"effective_from": "desc"},
    )
    if not m:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "No active seasonal multiplier for the current date."},
        )
    return _to_mult_response(m)


async def create_seasonal_multiplier(
    data: schemas.CreateSeasonalMultiplierRequest, created_by_id: str
) -> schemas.SeasonalMultiplierResponse:
    if data.effective_from and data.effective_to:
        overlap = await db.seasonal_multipliers.find_first(
            where={
                "quarter": data.quarter,
                "OR": [
                    {
                        "effective_from": {"lte": data.effective_to},
                        "effective_to": {"gte": data.effective_from},
                    }
                ],
            }
        )
        if overlap:
            raise HTTPException(status_code=409, detail="CONFLICT – Overlapping effective dates for the same quarter")

    now = datetime.now()
    new_m = await db.seasonal_multipliers.create(
        data={
            "quarter": data.quarter,
            "label": data.label,
            "multiplier": str(data.multiplier),
            "effective_from": data.effective_from,
            "effective_to": data.effective_to,
            "created_by": created_by_id,
            "updated_by": created_by_id,
            "updated_at": now,
        }
    )
    return _to_mult_response(new_m)


async def update_seasonal_multiplier(
    mult_id: str, data: schemas.UpdateSeasonalMultiplierRequest, updated_by_id: str
) -> schemas.SeasonalMultiplierResponse:
    existing = await db.seasonal_multipliers.find_unique(where={"seasonal_multiplier_id": mult_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Multiplier not found")

    update_data = data.model_dump(exclude_unset=True)
    if "multiplier" in update_data:
        update_data["multiplier"] = str(update_data["multiplier"])
    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = await db.seasonal_multipliers.update(
        where={"seasonal_multiplier_id": mult_id}, data=update_data
    )
    return _to_mult_response(updated)


async def delete_seasonal_multiplier(mult_id: str) -> None:
    existing = await db.seasonal_multipliers.find_unique(where={"seasonal_multiplier_id": mult_id})
    if not existing:
        raise HTTPException(status_code=404, detail="NOT_FOUND – Multiplier not found")

    today = date.today()
    if existing.effective_from and existing.effective_from <= today:
        raise HTTPException(
            status_code=400,
            detail="VALIDATION_ERROR – Cannot delete a currently active or past multiplier",
        )

    await db.seasonal_multipliers.delete(where={"seasonal_multiplier_id": mult_id})