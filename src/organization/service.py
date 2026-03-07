"""src/organization/service.py — with Redis caching."""
import math
from typing import Optional
from datetime import datetime
from fastapi import HTTPException
from src.prisma.client import db
from src.organization import schemas
from src.common.cache import cache_get, cache_set, cache_delete, invalidate_pattern

# ─────────────────────────────────────────────────────────────────────────────
# TTLs (seconds)
# ─────────────────────────────────────────────────────────────────────────────
TTL_DEPT_TYPES   = 3600   # 1 hr  — almost static
TTL_DEPARTMENTS  = 3600   # 1 hr  — changes extremely rarely
TTL_DESIGNATIONS = 3600   # 1 hr  — almost static

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


# ─────────────────────────────────────────────────────────────────────────────
# Public invalidation helpers  (called after writes)
# ─────────────────────────────────────────────────────────────────────────────

async def invalidate_departments() -> None:
    """Wipe all department list/detail caches after any write."""
    await invalidate_pattern("org:departments:*")
    await invalidate_pattern("org:department:*")

async def invalidate_designations() -> None:
    await invalidate_pattern("org:designations:*")
    await invalidate_pattern("org:designation:*")


# ══════════════════════════════════════════════
#  DEPARTMENT SERVICE
# ══════════════════════════════════════════════

async def list_departments(
    page: int,
    limit: int,
    is_active: Optional[bool],
    search: Optional[str]
) -> schemas.DepartmentListResponse:

    key = _key_depts(page, limit, is_active, search)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DepartmentListResponse(**cached)

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
            manager=None,
            is_active=True,
            created_at=dept.created_at
        ))

    result = schemas.DepartmentListResponse(
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

    await cache_set(key, result.model_dump(), ttl=TTL_DEPARTMENTS)
    return result


async def get_department_detail(department_id: str) -> schemas.DepartmentDetailResponse:
    key = _key_dept(department_id)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DepartmentDetailResponse(**cached)

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

    result = schemas.DepartmentDetailResponse(
        department_id=dept.department_id,
        department_name=dept.department_name,
        department_code=dept.department_code,
        department_type=dept_type,
        manager=None,
        employee_count=len(emp_list),
        is_active=True,
        created_at=dept.created_at,
        updated_at=dept.updated_at
    )

    await cache_set(key, result.model_dump(), ttl=TTL_DEPARTMENTS)
    return result


async def create_department(
    data: schemas.CreateDepartmentRequest,
    created_by_id: str
) -> schemas.DepartmentCreatedResponse:
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

    # Invalidate list caches so the new department appears
    await invalidate_departments()

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
                   if k not in ("is_active",)}

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

    # Invalidate this dept's detail cache + all list pages
    await cache_delete(_key_dept(department_id))
    await invalidate_pattern("org:departments:*")

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
    key = _key_dept_types()
    cached = await cache_get(key)
    if cached is not None:
        return [schemas.DepartmentTypeResponse(**t) for t in cached]

    types = await db.department_types.find_many(order={"type_name": "asc"})
    result = [
        schemas.DepartmentTypeResponse(
            department_type_id=t.department_type_id,
            type_name=t.type_name,
            type_code=t.type_code
        )
        for t in types
    ]

    await cache_set(key, [r.model_dump() for r in result], ttl=TTL_DEPT_TYPES)
    return result


# ══════════════════════════════════════════════
#  DESIGNATION SERVICE
# ══════════════════════════════════════════════

async def list_designations(
    page: int,
    limit: int,
    is_active: Optional[bool]
) -> schemas.DesignationListResponse:

    key = _key_desigs(page, limit, is_active)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DesignationListResponse(**cached)

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
            is_active=True,
            created_at=d.created_at
        )
        for d in designations
    ]

    result = schemas.DesignationListResponse(
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

    await cache_set(key, result.model_dump(), ttl=TTL_DESIGNATIONS)
    return result


async def get_designation_detail(designation_id: str) -> schemas.DesignationDetailResponse:
    key = _key_desig(designation_id)
    cached = await cache_get(key)
    if cached is not None:
        return schemas.DesignationDetailResponse(**cached)

    desig = await db.designations.find_unique(
        where={"designation_id": designation_id},
        include={"employees_employees_designation_idTodesignations": True}
    )

    if not desig:
        raise HTTPException(status_code=404, detail="Designation not found")

    emp_list = desig.employees_employees_designation_idTodesignations or []

    result = schemas.DesignationDetailResponse(
        designation_id=desig.designation_id,
        designation_name=desig.designation_name,
        designation_code=desig.designation_code,
        level=desig.level,
        description=None,
        employee_count=len(emp_list),
        is_active=True,
        created_at=desig.created_at,
        updated_at=desig.updated_at
    )

    await cache_set(key, result.model_dump(), ttl=TTL_DESIGNATIONS)
    return result


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

    await invalidate_designations()

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
                   if k not in ("is_active", "description")}

    if not update_data:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    await db.designations.update(
        where={"designation_id": designation_id},
        data=update_data
    )

    # Bust this specific detail + all list pages
    await cache_delete(_key_desig(designation_id))
    await invalidate_pattern("org:designations:*")

    return await get_designation_detail(designation_id)