"""
src/employees/internal_router.py
──────────────────────────────────
Internal-only endpoints consumed by the Analytics service.

Routes are written as /internal/employees/... with NO APIRouter prefix.
In employees/main.py: app.include_router(internal_router)  ← no prefix

Endpoints
─────────
  GET /internal/employees/active-count
      Returns {now, last_month} for the Analytics active_users KPI.

  GET /internal/employees/departments-with-members          ← NEW
      Returns every department with its member list (employee_id,
      username, designation_name) so the Analytics service can build
      team reports without touching Prisma directly.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter

from src.prisma.client import db

router = APIRouter(tags=["Internal"])


@router.get("/internal/employees/active-count")
async def active_employee_count():
    """
    Returns {now: int, last_month: int} for the Analytics dashboard
    active_users KPI. Called by internal_client.get_active_users_count().
    """
    from dateutil.relativedelta import relativedelta

    now              = datetime.now(timezone.utc)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_start = this_month_start - relativedelta(months=1)

    status = await db.status_master.find_first(where={"status_code": "ACTIVE"})
    if not status:
        return {"now": 0, "last_month": 0}

    now_count, last_month_count = await asyncio.gather(
        db.employees.count(where={"status_id": status.status_id}),
        db.employees.count(where={
            "status_id":  status.status_id,
            "created_at": {"lt": last_month_start},
        }),
    )
    return {"now": now_count, "last_month": last_month_count}

@router.get("/internal/employees/{employee_id}/manager-email")
async def get_manager_email(employee_id: str):
    from fastapi import HTTPException
    emp = await db.employees.find_unique(where={"employee_id": employee_id})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.manager_id is None:
        raise HTTPException(status_code=404, detail="Employee has no manager")
    manager = await db.employees.find_unique(
        where={"employee_id": str(emp.manager_id)}
    )
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")
    return {"email": manager.email}

@router.get("/internal/employees/departments-with-members")
async def departments_with_members():
    """
    Returns all departments, each with their member list.

    Called by internal_client.get_departments_with_members() which is
    used by the Analytics service to build team reports without importing
    Prisma directly (Analytics owns zero tables).

    Response shape:
    [
      {
        "department_id":   "...",
        "department_name": "Engineering",
        "members": [
          {
            "employee_id":        "...",
            "username":           "alice",
            "designation_name":   "Senior Engineer"
          },
          ...
        ]
      },
      ...
    ]
    """
    departments = await db.departments.find_many(
        order={"department_name": "asc"},
    )

    employees = await db.employees.find_many(
        include={"designations_employees_designation_idTodesignations": True},
    )

    # Group employees by department_id
    members_by_dept: dict[str, list] = {}
    for emp in employees:
        dept_id = str(emp.department_id) if emp.department_id else None
        if not dept_id:
            continue
        desig = emp.designations_employees_designation_idTodesignations
        members_by_dept.setdefault(dept_id, []).append({
            "employee_id":      str(emp.employee_id),
            "username":         emp.username,
            "designation_name": desig.designation_name if desig else "N/A",
        })

    return [
        {
            "department_id":   str(dept.department_id),
            "department_name": dept.department_name,
            "members":         members_by_dept.get(str(dept.department_id), []),
        }
        for dept in departments
    ]