import logging
import math
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from passlib.context import CryptContext
from fastapi import HTTPException, status
from src.prisma.client import db
from src.employees import schemas
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType
from src.common.cache import cache_delete, invalidate_pattern

logger = logging.getLogger(__name__)


def _get_notif_service() -> NotificationService:
    """
    Always returns a NotificationService with the live Redis client.
    Called at request time (not import time) so Redis is guaranteed
    to be connected when this runs.
    """
    try:
        from src.notifications.redis_client import get_redis
        r = get_redis()
    except RuntimeError:
        r = None
    return NotificationService(db, redis=r)


# ─────────────────────────────────────────────────────────────────────────────
# Cache invalidation helpers
#
# This service does NOT cache its own reads (too many filter combos, security
# sensitive data). It IS responsible for busting caches held by other services
# whenever an employee is created, updated, or deactivated.
# ─────────────────────────────────────────────────────────────────────────────

async def _invalidate_employee_caches(employee_id: str) -> None:
    """
    Bust all cross-service cache entries that reference this employee.
    Call after any write that changes employee data.
    """
    await cache_delete(f"wallets:employee:{employee_id}")          # wallet service
    await cache_delete(f"dashboard:platform:{employee_id}")        # analytics: platform stats
    await cache_delete(f"dashboard:reviews:{employee_id}")         # analytics: recent reviews
    await cache_delete("roles:employees")                          # roles service: employee-role list
    await cache_delete("dashboard:leaderboard")                    # analytics: leaderboard
    await invalidate_pattern("dashboard:team:*")                   # analytics: team reports
    await cache_delete("dashboard:teams")                          # analytics: teams summary
    logger.debug("cache invalidated for employee=%s", employee_id)


# ─────────────────────────────────────────────────────────────────────────────

# Password Hashing Config
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


async def list_employees(
    page: int,
    limit: int,
    department_id: Optional[UUID] = None,
    designation_id: Optional[UUID] = None,
    status_id: Optional[UUID] = None,
    manager_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "created_at",
    sort_order: Optional[str] = "desc",
) -> schemas.EmployeeListResponse:
    # Not cached — too many filter/sort combinations produce near-unique keys
    # that almost never get a second hit. Cache hit rate would be near zero.

    where_clause = {}
    and_conditions = []

    if department_id:
        and_conditions.append({"department_id": str(department_id)})
    if designation_id:
        and_conditions.append({"designation_id": str(designation_id)})
    if status_id:
        and_conditions.append({"status_id": str(status_id)})
    if manager_id:
        and_conditions.append({"manager_id": str(manager_id)})

    if is_active is not None:
        if is_active:
            and_conditions.append({"status_master_employees_status_idTostatus_master": {"is": {"status_code": "ACTIVE"}}})
        else:
            and_conditions.append({"status_master_employees_status_idTostatus_master": {"is_not": {"status_code": "ACTIVE"}}})

    if search:
        and_conditions.append({
            "OR": [
                {"username": {"contains": search, "mode": "insensitive"}},
                {"email":    {"contains": search, "mode": "insensitive"}},
            ]
        })

    if and_conditions:
        where_clause["AND"] = and_conditions

    total_count = await db.employees.count(where=where_clause)
    total_pages = math.ceil(total_count / limit)
    skip        = (page - 1) * limit

    allowed_sorts = ["created_at", "username", "date_of_joining"]
    sort_field    = sort_by if sort_by in allowed_sorts else "created_at"
    order         = sort_order if sort_order in ["asc", "desc"] else "desc"

    employees = await db.employees.find_many(
        where=where_clause,
        skip=skip,
        take=limit,
        order={sort_field: order},
        include={
            "departments_employees_department_idTodepartments":     True,
            "designations_employees_designation_idTodesignations":  True,
            "status_master_employees_status_idTostatus_master":     True,
            "employees_employees_manager_idToemployees":            True,
        },
    )

    data = []
    for emp in employees:
        dept  = emp.departments_employees_department_idTodepartments
        desig = emp.designations_employees_designation_idTodesignations
        stat  = emp.status_master_employees_status_idTostatus_master
        mgr   = emp.employees_employees_manager_idToemployees
        is_emp_active = stat.status_code == "ACTIVE" if stat else False

        data.append(schemas.EmployeeListItem(
            employee_id=emp.employee_id,
            username=emp.username,
            email=emp.email,
            designation_id=desig.designation_id if desig else None,
            designation_name=desig.designation_name if desig else None,
            department_id=dept.department_id if dept else None,
            department_name=dept.department_name if dept else None,
            manager_id=mgr.employee_id if mgr else None,
            manager_name=mgr.username if mgr else None,
            date_of_joining=emp.date_of_joining,
            status_id=stat.status_id if stat else None,
            status_name=stat.status_name if stat else None,
            is_active=is_emp_active,
            created_at=emp.created_at,
            updated_at=emp.updated_at,
        ))

    return schemas.EmployeeListResponse(
        data=data,
        pagination=schemas.PaginationMeta(
            current_page=page,
            per_page=limit,
            total=total_count,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    )


async def get_employee_detail(employee_id: str):
    # Not cached — includes wallet balance, roles, and status.
    # Stale data here could surface wrong permissions or balance to the UI.
    emp = await db.employees.find_unique(
        where={"employee_id": employee_id},
        include={
            "departments_employees_department_idTodepartments": {
                "include": {"department_types": True}
            },
            "designations_employees_designation_idTodesignations":  True,
            "status_master_employees_status_idTostatus_master":     True,
            "employees_employees_manager_idToemployees":            True,
            "wallets_wallets_employee_idToemployees":               True,
            "employee_roles_employee_roles_employee_idToemployees": {
                "where":   {"is_active": True},
                "include": {"roles": True},
            },
        },
    )

    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    emp_roles  = emp.employee_roles_employee_roles_employee_idToemployees
    roles_list = []
    if emp_roles:
        for er in emp_roles:
            if er.roles:
                roles_list.append(schemas.RoleResponse(
                    role_id=er.roles.role_id,
                    role_name=er.roles.role_name,
                    role_code=er.roles.role_code,
                ))

    dept          = emp.departments_employees_department_idTodepartments
    dept_type_resp = None
    if dept and dept.department_types:
        dept_type_resp = schemas.DepartmentTypeResponse(
            type_name=dept.department_types.type_name,
            type_code=dept.department_types.type_code,
        )

    stat      = emp.status_master_employees_status_idTostatus_master
    is_active = stat.status_code == "ACTIVE" if stat else False
    mgr       = emp.employees_employees_manager_idToemployees
    wallet    = emp.wallets_wallets_employee_idToemployees

    return schemas.EmployeeDetailResponse(
        employee_id=emp.employee_id,
        username=emp.username,
        email=emp.email,
        date_of_joining=emp.date_of_joining,
        is_active=is_active,
        designation=schemas.DesignationResponse(
            designation_id=emp.designations_employees_designation_idTodesignations.designation_id,
            designation_name=emp.designations_employees_designation_idTodesignations.designation_name,
            designation_code=emp.designations_employees_designation_idTodesignations.designation_code,
            level=emp.designations_employees_designation_idTodesignations.level,
        ) if emp.designations_employees_designation_idTodesignations else None,
        department=schemas.DepartmentResponse(
            department_id=dept.department_id,
            department_name=dept.department_name,
            department_code=dept.department_code,
            department_type=dept_type_resp,
        ) if dept else None,
        manager=schemas.ManagerResponse(
            employee_id=mgr.employee_id,
            username=mgr.username,
            email=mgr.email,
        ) if mgr else None,
        status=schemas.StatusResponse(
            status_id=stat.status_id,
            status_code=stat.status_code,
            status_name=stat.status_name,
        ) if stat else None,
        wallet=schemas.WalletResponse(
            wallet_id=wallet.wallet_id,
            available_points=wallet.available_points,
            redeemed_points=wallet.redeemed_points,
            total_earned_points=wallet.total_earned_points,
            version=wallet.version,
        ) if wallet else None,
        roles=roles_list,
        created_at=emp.created_at,
        created_by=emp.created_by,
        updated_at=emp.updated_at,
        updated_by=emp.updated_by,
    )


async def create_employee(data: schemas.CreateEmployeeRequest, created_by_id: str):
    existing = await db.employees.find_first(
        where={"OR": [{"username": data.username}, {"email": data.email}]}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Username or Email already exists")

    default_role = await db.roles.find_unique(where={"role_code": "EMPLOYEE"})
    if not default_role:
        raise HTTPException(status_code=500, detail="Default 'EMPLOYEE' role not found")

    hashed_pwd = get_password_hash(data.password)
    now        = datetime.now()

    try:
        async with db.tx() as transaction:
            # A. Create Employee
            new_emp = await transaction.employees.create(
                data={
                    "username":        data.username,
                    "email":           data.email,
                    "password_hash":   hashed_pwd,
                    "date_of_joining": datetime.combine(data.date_of_joining, datetime.min.time()).replace(tzinfo=timezone.utc),
                    "date_of_birth":   datetime.combine(data.date_of_birth, datetime.min.time()).replace(tzinfo=timezone.utc) if data.date_of_birth else None,
                    "updated_at":      now,
                    "designation_id":  str(data.designation_id),
                    "department_id":   str(data.department_id),
                    "status_id":       str(data.status_id),
                    "manager_id":      str(data.manager_id),
                    "created_by":      created_by_id,
                    "updated_by":      created_by_id,
                },
                include={"status_master_employees_status_idTostatus_master": True},
            )

            # B. Create Wallet
            wallet = await transaction.wallets.create(
                data={
                    "available_points": 0,
                    "updated_at":       now,
                    "employee_id":      new_emp.employee_id,
                    "created_by":       created_by_id,
                    "updated_by":       created_by_id,
                }
            )

            # C. Assign default EMPLOYEE role
            await transaction.employee_roles.create(
                data={
                    "assigned_at": now,
                    "updated_at":  now,
                    "employee_id": new_emp.employee_id,
                    "role_id":     default_role.role_id,
                    "created_by":  created_by_id,
                    "updated_by":  created_by_id,
                    "assigned_by": created_by_id,
                }
            )

            is_active = (
                new_emp.status_master_employees_status_idTostatus_master.status_code == "ACTIVE"
                if new_emp.status_master_employees_status_idTostatus_master else False
            )

            response = schemas.EmployeeCreatedResponse(
                employee_id=new_emp.employee_id,
                username=new_emp.username,
                email=new_emp.email,
                designation_id=new_emp.designation_id,
                department_id=new_emp.department_id,
                manager_id=new_emp.manager_id,
                date_of_joining=new_emp.date_of_joining,
                status_id=new_emp.status_id,
                is_active=is_active,
                created_at=new_emp.created_at,
                created_by=new_emp.created_by,
                wallet=schemas.WalletResponse(
                    wallet_id=wallet.wallet_id,
                    available_points=wallet.available_points,
                    redeemed_points=wallet.redeemed_points,
                    total_earned_points=wallet.total_earned_points,
                    version=wallet.version,
                ),
            )

        # ── Post-commit: invalidate caches & send welcome notification ─────
        await _invalidate_employee_caches(new_emp.employee_id)

        try:
            await _get_notif_service().create_notification(
                employee_id=new_emp.employee_id,
                title="Welcome to the platform! 🎉",
                message=(
                    f"Hi {new_emp.username}, your account is ready. "
                    "You can now give and receive recognition from your peers."
                ),
                type=NotificationType.SYSTEM,
            )
        except Exception:
            logger.exception(
                "Welcome notification failed for employee %s — account was created successfully",
                new_emp.employee_id,
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating employee")
        raise HTTPException(status_code=400, detail=f"Creation failed: {str(e)}")


async def update_employee(
    employee_id: str, data: schemas.UpdateEmployeeRequest, updated_by_id: str
):
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not update_data:
        return await get_employee_detail(employee_id)

    for key in ["designation_id", "department_id", "manager_id", "status_id"]:
        if key in update_data and update_data[key]:
            update_data[key] = str(update_data[key])

    if "date_of_birth" in update_data:
        dob = update_data["date_of_birth"]
        update_data["date_of_birth"] = (
            datetime.combine(dob, datetime.min.time()).replace(tzinfo=timezone.utc)
            if dob else None
        )

    update_data["updated_by"] = updated_by_id
    update_data["updated_at"] = datetime.now()

    await db.employees.update(
        where={"employee_id": employee_id},
        data=update_data,
    )

    # Bust all cross-service caches for this employee
    await _invalidate_employee_caches(employee_id)

    return await get_employee_detail(employee_id)


async def patch_employee(employee_id: str, updated_by_id: str):
    inactive_status = await db.status_master.find_first(
        where={"status_code": "INACTIVE"}
    )
    if not inactive_status:
        raise HTTPException(status_code=500, detail="INACTIVE status not found")

    await db.employees.update(
        where={"employee_id": employee_id},
        data={
            "status_id":  inactive_status.status_id,
            "updated_by": updated_by_id,
            "updated_at": datetime.now(),
        },
    )

    # Bust all cross-service caches — deactivation affects leaderboard,
    # team reports, active user counts, and role assignments.
    await _invalidate_employee_caches(employee_id)

    return True