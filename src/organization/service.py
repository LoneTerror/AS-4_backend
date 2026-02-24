import math
from typing import Optional
from uuid import UUID
from datetime import datetime
from fastapi import HTTPException
from src.prisma.client import db

# Corrected the import path
from src.organization import schemas


# ══════════════════════════════════════════════
#  DEPARTMENT SERVICE
# ══════════════════════════════════════════════

def _build_dept_response(dept, with_count: bool = False, employee_count: int = 0) -> dict:
    """Helper: build department dict from Prisma object."""
    dept_type = None
    if dept.department_types:
        dept_type = schemas.DepartmentTypeResponse(
            department_type_id=dept.department_types.department_type_id,
            type_name=dept.department_types.type_name,
            type_code=dept.department_types.type_code
        )

    manager = None
    # manager_id is stored as a scalar FK; we need the manager employee record
    # The service functions that need manager details pass manager_record separately
    return dept_type, manager


async def _get_manager(manager_id: Optional[str]):
    if not manager_id:
        return None
    mgr = await db.employees.find_unique(where={"employee_id": manager_id})
    return mgr


async def list_departments(
    page: int,
    limit: int,
    is_active: Optional[bool],
    search: Optional[str]
) -> schemas.DepartmentListResponse:

    where: dict = {}
    and_conditions = []

    if is_active is not None:
        # departments don't have is_active column — derive from employee status or skip
        # Per schema departments has no is_active; we'll treat is_active as a filter
        # on whether department has a manager (active use). Skip if not in schema.
        pass  # no is_active column on departments in schema — we'll add a virtual field below

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

        # Fetch manager separately (manager_id is a scalar on the dept? — no, it's not)
        # Per schema, departments does NOT have a manager_id column.
        # Manager link is: employees.department_id -> departments
        # The API spec says manager comes from employees who manage this dept — 
        # we'll skip manager in list view (not in schema) or return None.

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
    types = await db.department_types.find_many(order={"type_name": "asc"})
    return types


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