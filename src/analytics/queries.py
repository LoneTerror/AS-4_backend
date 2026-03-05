"""Prisma ORM queries for the dashboard summary endpoint."""
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from src.prisma.client import db


def _month_range(dt: datetime):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, start + relativedelta(months=1)


def _now():
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════
#  Existing — unchanged
# ══════════════════════════════════════════════════════════════

async def get_employee_with_details(employee_id: str):
    return await db.employees.find_unique(
        where={"employee_id": employee_id},
        include={
            "designations_employees_designation_idTodesignations": True,
            "departments_employees_department_idTodepartments": True,
        }
    )


async def get_recent_reviews(employee_id: str, limit: int = 5):
    return await db.reviews.find_many(
        where={"receiver_id": employee_id},
        include={"employees_reviews_reviewer_idToemployees": True},
        order={"review_at": "desc"},
        take=limit,
    )


async def get_leaderboard(limit: int = 10):
    return await db.wallets.find_many(
        order={"total_earned_points": "desc"},
        take=limit,
        include={
            "employees_wallets_employee_idToemployees": {
                "include": {
                    "departments_employees_department_idTodepartments": True,
                }
            }
        },
    )


async def get_user_total_points(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    return wallet.available_points if wallet else 0


async def get_user_points_earned_this_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    start, end = _month_range(_now())
    types = await db.transaction_types.find_many(where={"is_credit": True})
    ids = [t.type_id for t in types]
    if not ids:
        return 0
    txns = await db.transactions.find_many(
        where={"wallet_id": wallet.wallet_id, "transaction_type_id": {"in": ids},
               "transaction_at": {"gte": start, "lt": end}}
    )
    return sum(t.amount for t in txns)


async def get_user_points_earned_last_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    types = await db.transaction_types.find_many(where={"is_credit": True})
    ids = [t.type_id for t in types]
    if not ids:
        return 0
    txns = await db.transactions.find_many(
        where={"wallet_id": wallet.wallet_id, "transaction_type_id": {"in": ids},
               "transaction_at": {"gte": start, "lt": end}}
    )
    return sum(t.amount for t in txns)


async def get_user_total_rewards_redeemed(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    return await db.reward_history.count(where={"wallet_id": wallet.wallet_id})


async def get_user_rewards_redeemed_this_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    start, end = _month_range(_now())
    return await db.reward_history.count(
        where={"wallet_id": wallet.wallet_id, "granted_at": {"gte": start, "lt": end}}
    )


async def get_user_rewards_redeemed_last_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reward_history.count(
        where={"wallet_id": wallet.wallet_id, "granted_at": {"gte": start, "lt": end}}
    )


async def get_user_total_reviews(employee_id: str) -> int:
    return await db.reviews.count(where={"receiver_id": employee_id})


async def get_user_reviews_this_month(employee_id: str) -> int:
    start, end = _month_range(_now())
    return await db.reviews.count(
        where={"receiver_id": employee_id, "review_at": {"gte": start, "lt": end}}
    )


async def get_user_reviews_last_month(employee_id: str) -> int:
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reviews.count(
        where={"receiver_id": employee_id, "review_at": {"gte": start, "lt": end}}
    )


async def get_active_users_count() -> int:
    s = await db.status_master.find_first(where={"status_code": "ACTIVE"})
    if not s:
        return 0
    return await db.employees.count(where={"status_id": s.status_id})


async def get_active_users_count_last_month() -> int:
    s = await db.status_master.find_first(where={"status_code": "ACTIVE"})
    if not s:
        return 0
    start, _ = _month_range(_now())
    return await db.employees.count(
        where={"status_id": s.status_id, "created_at": {"lt": start}}
    )


# ══════════════════════════════════════════════════════════════
#  Admin — Team Report queries
#
#  CRITICAL RULE: Never convert Prisma UUID objects to str().
#  Pass them directly as received from Prisma — the client
#  knows how to serialize them correctly for the next query.
#  String conversion breaks UUID equality matching in Prisma Python.
# ══════════════════════════════════════════════════════════════

async def get_all_departments():
    return await db.departments.find_many(order={"department_name": "asc"})


async def get_department_by_id(department_id: str):
    """department_id here comes from the HTTP path param — plain string is fine for find_unique."""
    return await db.departments.find_unique(where={"department_id": department_id})


async def get_employees_in_department(dept):
    """
    Pass the raw dept object returned by get_all_departments().
    Uses dept.department_id (native UUID object) directly — no str() conversion.
    Includes designation via the exact relation name from schema.prisma.
    """
    return await db.employees.find_many(
        where={"department_id": dept.department_id},
        include={
            "designations_employees_designation_idTodesignations": True,
        },
    )


async def get_wallet_for_employee(emp):
    """Pass the raw employee object. Uses emp.employee_id natively."""
    return await db.wallets.find_first(
        where={"employee_id": emp.employee_id}
    )


async def get_credit_type_ids() -> list:
    """Returns native type_id objects — safe to reuse in same-session queries."""
    rows = await db.transaction_types.find_many(where={"is_credit": True})
    return [r.type_id for r in rows]


async def get_points_this_month_for_wallet(wallet, credit_type_ids: list) -> int:
    """Pass the raw wallet object. Uses wallet.wallet_id natively."""
    if not credit_type_ids:
        return 0
    start, end = _month_range(_now())
    txns = await db.transactions.find_many(
        where={
            "wallet_id": wallet.wallet_id,
            "transaction_type_id": {"in": credit_type_ids},
            "transaction_at": {"gte": start, "lt": end},
        }
    )
    return sum(t.amount for t in txns)


async def get_review_count_for_employee(emp) -> int:
    """Pass the raw employee object."""
    return await db.reviews.count(where={"receiver_id": emp.employee_id})


async def get_reviews_this_month_for_employee(emp) -> int:
    """Pass the raw employee object."""
    start, end = _month_range(_now())
    return await db.reviews.count(
        where={"receiver_id": emp.employee_id, "review_at": {"gte": start, "lt": end}}
    )


async def get_rewards_redeemed_for_wallet(wallet) -> int:
    """Pass the raw wallet object."""
    return await db.reward_history.count(where={"wallet_id": wallet.wallet_id})