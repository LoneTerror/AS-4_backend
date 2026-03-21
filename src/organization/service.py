# src/organization/service.py
import math
from typing import Optional
from datetime import datetime
from fastapi import HTTPException, Request
from src.prisma.client import db
from src.organization import schemas
from src.common.audit import audit_ctx
from src.common.cache import cache_get, cache_set, cache_delete, invalidate_pattern

TTL_DEPT_TYPES   = 3600
TTL_DEPARTMENTS  = 3600
TTL_DESIGNATIONS = 3600

# ─────────────────────────────────────────────────────────────────────────────
# Cache-key helpers
# ─────────────────────────────────────────────────────────────────────────────

def _key_dept_types()                              -> str: return "org:department_types"
def _key_depts(page, limit, is_active, search)     -> str:
    return f"org:departments:{page}:{limit}:{is_active}:{search}"
def _key_dept(dept_id: str)                        -> str: return f"org:department:{dept_id}"
def _key_desigs(page, limit, is_active)            -> str:
    return f"org:designations:{page}:{limit}:{is_active}"
def _key_desig(desig_id: str)                      -> str: return f"org:designation:{desig_id}"

async def invalidate_departments() -> None:
    await invalidate_pattern("org:departments:*")
    await invalidate_pattern("org:department:*")

async def invalidate_designations() -> None:
    await invalidate_pattern("org:designations:*")
    await invalidate_pattern("org:designation:*")


# ══════════════════════════════════════════════
#  DEPARTMENT SERVICE
# ══════════════════════════════════════════════

async def list_departments(
    page: int, limit: int, is_active: Optional[bool], search: Optional[str]
) -> schemas.DepartmentListResponse:

    key    = _key_depts(page, limit, is_active, search)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DepartmentListResponse(**cached)

    where: dict  = {}
    and_conditions = []
    if is_active is not None:
        and_conditions.append({"is_active": is_active})
    if search:
        and_conditions.append({
            "OR": [
                {"department_name": {"contains": search, "mode": "insensitive"}},
                {"department_code": {"contains": search, "mode": "insensitive"}},
            ]
        })
    if and_conditions:
        where["AND"] = and_conditions

    total       = await db.departments.count(where=where)
    total_pages = math.ceil(total / limit) if total else 1
    skip        = (page - 1) * limit

    departments = await db.departments.find_many(
        where=where, skip=skip, take=limit,
        order={"created_at": "desc"},
        include={"department_types": True},
    )

    data = []
    for dept in departments:
        dept_type = None
        if dept.department_types:
            dept_type = schemas.DepartmentTypeResponse(
                department_type_id=dept.department_types.department_type_id,
                type_name=dept.department_types.type_name,
                type_code=dept.department_types.type_code,
            )
        data.append(schemas.DepartmentListItem(
            department_id=dept.department_id,
            department_name=dept.department_name,
            department_code=dept.department_code,
            department_type=dept_type,
            manager=None,
            is_active=True,
            created_at=dept.created_at,
        ))

    result = schemas.DepartmentListResponse(
        data=data,
        pagination=schemas.PaginationMeta(
            current_page=page, per_page=limit, total=total,
            total_pages=total_pages,
            has_next=page < total_pages, has_previous=page > 1,
        ),
    )
    await cache_set(key, result.model_dump(), ttl=TTL_DEPARTMENTS)
    return result


async def get_department_detail(department_id: str) -> schemas.DepartmentDetailResponse:
    key    = _key_dept(department_id)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DepartmentDetailResponse(**cached)

    dept = await db.departments.find_unique(
        where={"department_id": department_id},
        include={
            "department_types": True,
            "employees_employees_department_idTodepartments": True,
        },
    )
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    dept_type = None
    if dept.department_types:
        dept_type = schemas.DepartmentTypeResponse(
            department_type_id=dept.department_types.department_type_id,
            type_name=dept.department_types.type_name,
            type_code=dept.department_types.type_code,
        )

    emp_list = dept.employees_employees_department_idTodepartments or []
    result   = schemas.DepartmentDetailResponse(
        department_id=dept.department_id,
        department_name=dept.department_name,
        department_code=dept.department_code,
        department_type=dept_type,
        manager=None,
        employee_count=len(emp_list),
        is_active=True,
        created_at=dept.created_at,
        updated_at=dept.updated_at,
    )
    await cache_set(key, result.model_dump(), ttl=TTL_DEPARTMENTS)
    return result


async def create_department(
    data: schemas.CreateDepartmentRequest,
    created_by_id: str,
    request: Optional[Request] = None,
) -> schemas.DepartmentCreatedResponse:

    existing = await db.departments.find_first(where={
        "OR": [
            {"department_name": data.department_name},
            {"department_code": data.department_code},
        ]
    })
    if existing:
        raise HTTPException(status_code=400, detail="Department name or code already exists")

    dept_type = await db.department_types.find_unique(
        where={"department_type_id": str(data.department_type_id)}
    )
    if not dept_type:
        raise HTTPException(status_code=400, detail="Department type not found")

    new_dept = None
    async with audit_ctx(
        user_id    = created_by_id,
        request    = request,
        table_name = "departments",
        record_id  = lambda: str(new_dept.department_id),
        operation  = "INSERT",
        new_values = lambda: new_dept.model_dump(),
    ):
        new_dept = await db.departments.create(
            data={
                "department_name":    data.department_name,
                "department_code":    data.department_code,
                "department_type_id": str(data.department_type_id),
                "created_by":         created_by_id,
                "updated_by":         created_by_id,
                "updated_at":         datetime.now(),
            },
            include={"department_types": True},
        )

    await invalidate_departments()

    dept_type_resp = None
    if new_dept.department_types:
        dept_type_resp = schemas.DepartmentTypeResponse(
            department_type_id=new_dept.department_types.department_type_id,
            type_name=new_dept.department_types.type_name,
            type_code=new_dept.department_types.type_code,
        )
    return schemas.DepartmentCreatedResponse(
        department_id=new_dept.department_id,
        department_name=new_dept.department_name,
        department_code=new_dept.department_code,
        department_type=dept_type_resp,
        manager=None,
        is_active=True,
        created_at=new_dept.created_at,
        created_by=new_dept.created_by,
    )


async def update_department(
    department_id: str,
    data: schemas.UpdateDepartmentRequest,
    updated_by_id: str,
    request: Optional[Request] = None,
) -> schemas.DepartmentUpdatedResponse:

    existing = await db.departments.find_unique(where={"department_id": department_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Department not found")

    old_snapshot = existing.model_dump()

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()
                   if k not in ("is_active",)}
    if "department_type_id" in update_data and update_data["department_type_id"]:
        update_data["department_type_id"] = str(update_data["department_type_id"])
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = None
    async with audit_ctx(
        user_id    = updated_by_id,
        request    = request,
        table_name = "departments",
        record_id  = department_id,
        operation  = "UPDATE",
        old_values = old_snapshot,
        new_values = lambda: updated.model_dump(),
    ):
        updated = await db.departments.update(
            where={"department_id": department_id},
            data=update_data,
            include={"department_types": True},
        )

    await cache_delete(_key_dept(department_id))
    await invalidate_pattern("org:departments:*")

    dept_type_resp = None
    if updated.department_types:
        dept_type_resp = schemas.DepartmentTypeResponse(
            department_type_id=updated.department_types.department_type_id,
            type_name=updated.department_types.type_name,
            type_code=updated.department_types.type_code,
        )
    return schemas.DepartmentUpdatedResponse(
        department_id=updated.department_id,
        department_name=updated.department_name,
        department_code=updated.department_code,
        department_type=dept_type_resp,
        manager=None,
        is_active=True,
        updated_at=updated.updated_at,
        updated_by=updated.updated_by,
    )


async def list_department_types() -> list[schemas.DepartmentTypeResponse]:
    key    = _key_dept_types()
    cached = await cache_get(key)
    if cached is not None:
        return [schemas.DepartmentTypeResponse(**t) for t in cached]

    types  = await db.department_types.find_many(order={"type_name": "asc"})
    result = [
        schemas.DepartmentTypeResponse(
            department_type_id=t.department_type_id,
            type_name=t.type_name,
            type_code=t.type_code,
        )
        for t in types
    ]
    await cache_set(key, [r.model_dump() for r in result], ttl=TTL_DEPT_TYPES)
    return result


# ══════════════════════════════════════════════
#  DESIGNATION SERVICE
# ══════════════════════════════════════════════

async def list_designations(
    page: int, limit: int, is_active: Optional[bool]
) -> schemas.DesignationListResponse:

    key    = _key_desigs(page, limit, is_active)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DesignationListResponse(**cached)

    where: dict = {}
    if is_active is not None:
        where["is_active"] = is_active

    total       = await db.designations.count(where=where)
    total_pages = math.ceil(total / limit) if total else 1
    skip        = (page - 1) * limit

    designations = await db.designations.find_many(
        where=where, skip=skip, take=limit, order={"level": "asc"}
    )
    data = [
        schemas.DesignationListItem(
            designation_id=d.designation_id,
            designation_name=d.designation_name,
            designation_code=d.designation_code,
            level=d.level,
            is_active=d.is_active,
            created_at=d.created_at,
        )
        for d in designations
    ]
    result = schemas.DesignationListResponse(
        data=data,
        pagination=schemas.PaginationMeta(
            current_page=page, per_page=limit, total=total,
            total_pages=total_pages,
            has_next=page < total_pages, has_previous=page > 1,
        ),
    )
    await cache_set(key, result.model_dump(), ttl=TTL_DESIGNATIONS)
    return result


async def get_designation_detail(designation_id: str) -> schemas.DesignationDetailResponse:
    key    = _key_desig(designation_id)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DesignationDetailResponse(**cached)

    desig = await db.designations.find_unique(
        where={"designation_id": designation_id},
        include={"employees_employees_designation_idTodesignations": True},
    )
    if not desig:
        raise HTTPException(status_code=404, detail="Designation not found")

    emp_list = desig.employees_employees_designation_idTodesignations or []
    result   = schemas.DesignationDetailResponse(
        designation_id=desig.designation_id,
        designation_name=desig.designation_name,
        designation_code=desig.designation_code,
        level=desig.level,
        description=desig.description,
        employee_count=len(emp_list),
        is_active=desig.is_active,
        created_at=desig.created_at,
        updated_at=desig.updated_at,
    )
    await cache_set(key, result.model_dump(), ttl=TTL_DESIGNATIONS)
    return result


async def create_designation(
    data: schemas.CreateDesignationRequest,
    created_by_id: str,
    request: Optional[Request] = None,
) -> schemas.DesignationListItem:

    existing = await db.designations.find_first(where={
        "OR": [
            {"designation_name": data.designation_name},
            {"designation_code": data.designation_code},
        ]
    })
    if existing:
        raise HTTPException(status_code=400, detail="Designation name or code already exists")

    new_desig = None
    async with audit_ctx(
        user_id    = created_by_id,
        request    = request,
        table_name = "designations",
        record_id  = lambda: str(new_desig.designation_id),
        operation  = "INSERT",
        new_values = lambda: new_desig.model_dump(),
    ):
        new_desig = await db.designations.create(
            data={
                "designation_name": data.designation_name,
                "designation_code": data.designation_code,
                "level":            data.level,
                "description":      data.description,
                "created_by":       created_by_id,
                "updated_by":       created_by_id,
                "updated_at":       datetime.now(),
            }
        )

    await invalidate_designations()
    return schemas.DesignationListItem(
        designation_id=new_desig.designation_id,
        designation_name=new_desig.designation_name,
        designation_code=new_desig.designation_code,
        level=new_desig.level,
        is_active=True,
        created_at=new_desig.created_at,
    )


async def update_designation(
    designation_id: str,
    data: schemas.UpdateDesignationRequest,
    updated_by_id: str,
    request: Optional[Request] = None,
) -> schemas.DesignationDetailResponse:

    existing = await db.designations.find_unique(where={"designation_id": designation_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Designation not found")

    old_snapshot = existing.model_dump()

    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()
                   if k not in ("is_active",)}
    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    new_code = update_data.get("designation_code")
    if new_code and new_code != existing.designation_code:
        conflict = await db.designations.find_first(where={
            "designation_code": new_code,
            "NOT": {"designation_id": designation_id},
        })
        if conflict:
            raise HTTPException(status_code=400,
                                detail=f"Designation code '{new_code}' is already in use.")

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = None
    async with audit_ctx(
        user_id    = updated_by_id,
        request    = request,
        table_name = "designations",
        record_id  = designation_id,
        operation  = "UPDATE",
        old_values = old_snapshot,
        new_values = lambda: updated.model_dump(),
    ):
        updated = await db.designations.update(
            where={"designation_id": designation_id},
            data=update_data,
        )

    await cache_delete(_key_desig(designation_id))
    await invalidate_pattern("org:designations:*")
    return await get_designation_detail(designation_id)


# ══════════════════════════════════════════════
#  STATUS MASTER SERVICE
# ══════════════════════════════════════════════

async def list_statuses(entity_type: Optional[str] = None) -> list[schemas.StatusResponse]:
    where = {}
    if entity_type:
        where["entity_type"] = entity_type.upper()
    statuses = await db.status_master.find_many(where=where, order={"entity_type": "asc"})
    return [
        schemas.StatusResponse(
            status_id=st.status_id, status_code=st.status_code,
            status_name=st.status_name, description=st.description,
            entity_type=st.entity_type, created_at=st.created_at,
        )
        for st in statuses
    ]


async def get_status(status_id: str) -> schemas.StatusDetailResponse:
    st = await db.status_master.find_unique(where={"status_id": status_id})
    if not st:
        raise HTTPException(status_code=404, detail="Status not found")
    return schemas.StatusDetailResponse(
        status_id=st.status_id, status_code=st.status_code,
        status_name=st.status_name, description=st.description,
        entity_type=st.entity_type, created_at=st.created_at,
        updated_at=st.updated_at,
    )


async def create_status(
    data: schemas.CreateStatusRequest,
    created_by_id: str,
    request: Optional[Request] = None,
) -> schemas.StatusDetailResponse:

    existing = await db.status_master.find_unique(where={"status_code": data.status_code})
    if existing:
        raise HTTPException(status_code=409, detail="CONFLICT – status_code already exists")

    new_st = None
    async with audit_ctx(
        user_id    = created_by_id,
        request    = request,
        table_name = "status_master",
        record_id  = lambda: str(new_st.status_id),
        operation  = "INSERT",
        new_values = lambda: new_st.model_dump(),
    ):
        new_st = await db.status_master.create(
            data={
                "status_code": data.status_code,
                "status_name": data.status_name,
                "description": data.description,
                "entity_type": data.entity_type,
                "created_by":  created_by_id,
                "updated_by":  created_by_id,
                "updated_at":  datetime.now(),
            }
        )

    return schemas.StatusDetailResponse(
        status_id=new_st.status_id, status_code=new_st.status_code,
        status_name=new_st.status_name, description=new_st.description,
        entity_type=new_st.entity_type, created_at=new_st.created_at,
        updated_at=new_st.updated_at,
    )


async def update_status(
    status_id: str,
    data: schemas.UpdateStatusRequest,
    updated_by_id: str,
    request: Optional[Request] = None,
) -> schemas.StatusDetailResponse:

    existing = await db.status_master.find_unique(where={"status_id": status_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Status not found")

    old_snapshot = existing.model_dump()
    update_data  = data.model_dump(exclude_unset=True)
    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    updated = None
    async with audit_ctx(
        user_id    = updated_by_id,
        request    = request,
        table_name = "status_master",
        record_id  = status_id,
        operation  = "UPDATE",
        old_values = old_snapshot,
        new_values = lambda: updated.model_dump(),
    ):
        updated = await db.status_master.update(
            where={"status_id": status_id}, data=update_data
        )

    return schemas.StatusDetailResponse(
        status_id=updated.status_id, status_code=updated.status_code,
        status_name=updated.status_name, description=updated.description,
        entity_type=updated.entity_type, created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


# ══════════════════════════════════════════════
#  AUDIT LOGS SERVICE  (read-only viewer)
# ══════════════════════════════════════════════

async def list_audit_logs(
    page: int, limit: int,
    table_name: Optional[str], record_id: Optional[str],
    operation_type: Optional[str], performed_by: Optional[str],
    start_date: Optional[datetime], end_date: Optional[datetime],
) -> dict:
    where: dict = {}
    if table_name:      where["table_name"]     = {"contains": table_name, "mode": "insensitive"}
    if record_id:       where["record_id"]       = record_id
    if operation_type:  where["operation_type"]  = {"contains": operation_type.upper()}
    if performed_by:    where["performed_by"]    = performed_by
    if start_date or end_date:
        where["performed_at"] = {}
        if start_date: where["performed_at"]["gte"] = start_date
        if end_date:   where["performed_at"]["lte"] = end_date

    total       = await db.audit_log.count(where=where)
    total_pages = math.ceil(total / limit) if total else 1
    skip        = (page - 1) * limit

    # Fetch logs WITHOUT include — Prisma Python's include on a required
    # relation compiles to INNER JOIN, silently dropping any audit_log row
    # whose performed_by UUID has no matching employees record (e.g. sentinel
    # system UUID, or rows written by background consumers before the employee
    # relation can be resolved). We do a separate bulk employee lookup instead.
    logs = await db.audit_log.find_many(
        where=where, skip=skip, take=limit,
        order={"performed_at": "desc"},
    )

    # Bulk-resolve employee names in one query
    performer_ids = list({log.performed_by for log in logs})
    employees_map: dict = {}
    if performer_ids:
        emps = await db.employees.find_many(
            where={"employee_id": {"in": performer_ids}}
        )
        employees_map = {str(e.employee_id): e for e in emps}

    data = [
        schemas.AuditLogResponse(
            audit_id=log.audit_id, table_name=log.table_name,
            record_id=log.record_id, operation_type=log.operation_type,
            old_values=log.old_values, new_values=log.new_values,
            performed_by=log.performed_by, performed_at=log.performed_at,
            ip_address=log.ip_address, user_agent=log.user_agent,
            employee_name=(employees_map[log.performed_by].username
                           if log.performed_by in employees_map else None),
            employee_email=(employees_map[log.performed_by].email
                            if log.performed_by in employees_map else None),
        )
        for log in logs
    ]

    return {
        "data": data,
        "pagination": schemas.PaginationMeta(
            current_page=page, per_page=limit, total=total,
            total_pages=total_pages,
            has_next=page < total_pages, has_previous=page > 1,
        ),
    }


async def get_audit_log(audit_id: str) -> schemas.AuditLogResponse:
    log = await db.audit_log.find_unique(where={"audit_id": audit_id})
    if not log:
        raise HTTPException(status_code=404, detail="Audit log entry not found.")
    # Separate lookup — avoids INNER JOIN dropping rows with unresolved performed_by
    emp = await db.employees.find_unique(where={"employee_id": log.performed_by})
    return schemas.AuditLogResponse(
        audit_id=log.audit_id, table_name=log.table_name,
        record_id=log.record_id, operation_type=log.operation_type,
        old_values=log.old_values, new_values=log.new_values,
        performed_by=log.performed_by, performed_at=log.performed_at,
        ip_address=log.ip_address, user_agent=log.user_agent,
        employee_name=emp.username if emp else None,
        employee_email=emp.email   if emp else None,
    )