"""Prisma ORM queries for the dashboard summary endpoint — optimised."""
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from src.prisma.client import db


def _month_range(dt: datetime):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, start + relativedelta(months=1)

def _now():
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════
#  Shared lookups — fetched once, reused everywhere
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
        include={
            "employees_reviews_reviewer_idToemployees": True,
            "review_category_tags": True,
        },
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
#  Platform stats — BULK version
#  Single wallet fetch + single transaction fetch covers all
#  monthly point calculations. Replaces 6 wallet round-trips.
# ══════════════════════════════════════════════════════════════

async def get_platform_stats_bulk(employee_id: str) -> dict:
    """
    Replaces the 11 individual query functions used by get_platform_stats().
    Fetches wallet once, credit type IDs once, and transactions once per period.
    Returns a plain dict with all values needed by PlatformStats.
    """
    now   = _now()
    start_this, end_this = _month_range(now)
    start_last, end_last = _month_range(now - relativedelta(months=1))

    # Single wallet fetch for this employee
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})

    # Credit type IDs fetched once
    credit_types = await db.transaction_types.find_many(where={"is_credit": True})
    credit_ids   = [t.type_id for t in credit_types]

    if wallet and credit_ids:
        # Fetch this-month + last-month transactions in parallel — two queries total
        import asyncio
        txns_this, txns_last = await asyncio.gather(
            db.transactions.find_many(where={
                "wallet_id": wallet.wallet_id,
                "transaction_type_id": {"in": credit_ids},
                "transaction_at": {"gte": start_this, "lt": end_this},
            }),
            db.transactions.find_many(where={
                "wallet_id": wallet.wallet_id,
                "transaction_type_id": {"in": credit_ids},
                "transaction_at": {"gte": start_last, "lt": end_last},
            }),
        )
        pts_this = sum(t.amount for t in txns_this)
        pts_last = sum(t.amount for t in txns_last)
    else:
        pts_this = pts_last = 0

    import asyncio
    (
        rewards_total, rewards_this, rewards_last,
        reviews_total, reviews_this, reviews_last,
        active_now, active_last,
    ) = await asyncio.gather(
        # Rewards — wallet needed
        db.reward_history.count(where={"wallet_id": wallet.wallet_id}) if wallet else _zero(),
        db.reward_history.count(where={"wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start_this, "lt": end_this}}) if wallet else _zero(),
        db.reward_history.count(where={"wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start_last, "lt": end_last}}) if wallet else _zero(),
        # Reviews — just counts on employee_id
        db.reviews.count(where={"receiver_id": employee_id}),
        db.reviews.count(where={"receiver_id": employee_id,
            "review_at": {"gte": start_this, "lt": end_this}}),
        db.reviews.count(where={"receiver_id": employee_id,
            "review_at": {"gte": start_last, "lt": end_last}}),
        # Active users
        get_active_users_count(),
        get_active_users_count_last_month(),
    )

    return {
        "user_points":     wallet.available_points if wallet else 0,
        "pts_this":        pts_this,
        "pts_last":        pts_last,
        "rewards_total":   rewards_total,
        "rewards_this":    rewards_this,
        "rewards_last":    rewards_last,
        "reviews_total":   reviews_total,
        "reviews_this":    reviews_this,
        "reviews_last":    reviews_last,
        "active_now":      active_now,
        "active_last":     active_last,
    }


async def _zero():
    """Awaitable zero — used as a no-op placeholder in gather()."""
    return 0


# ══════════════════════════════════════════════════════════════
#  Team report queries
#  get_credit_type_ids() is now called ONCE in the service,
#  not once-per-employee. All others unchanged.
# ══════════════════════════════════════════════════════════════

async def get_all_departments():
    return await db.departments.find_many(order={"department_name": "asc"})


async def get_department_by_id(department_id: str):
    return await db.departments.find_unique(where={"department_id": department_id})


async def get_employees_in_department(dept):
    return await db.employees.find_many(
        where={"department_id": dept.department_id},
        include={
            "designations_employees_designation_idTodesignations": True,
        },
    )


async def get_wallet_for_employee(emp):
    return await db.wallets.find_first(where={"employee_id": emp.employee_id})


async def get_credit_type_ids() -> list:
    """Fetch once at service level and pass down — never call per-employee."""
    rows = await db.transaction_types.find_many(where={"is_credit": True})
    return [r.type_id for r in rows]


async def get_points_this_month_for_wallet(wallet, credit_type_ids: list) -> int:
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
    return await db.reviews.count(where={"receiver_id": emp.employee_id})


async def get_reviews_this_month_for_employee(emp) -> int:
    start, end = _month_range(_now())
    return await db.reviews.count(
        where={"receiver_id": emp.employee_id, "review_at": {"gte": start, "lt": end}}
    )


async def get_rewards_redeemed_for_wallet(wallet) -> int:
    return await db.reward_history.count(where={"wallet_id": wallet.wallet_id})


# ══════════════════════════════════════════════════════════════
#  Legacy individual functions — kept for backward compat
#  but should not be called in hot paths anymore.
# ══════════════════════════════════════════════════════════════

async def get_user_total_points(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    return wallet.available_points if wallet else 0

async def get_user_points_earned_this_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet: return 0
    start, end = _month_range(_now())
    types = await db.transaction_types.find_many(where={"is_credit": True})
    ids = [t.type_id for t in types]
    if not ids: return 0
    txns = await db.transactions.find_many(where={
        "wallet_id": wallet.wallet_id, "transaction_type_id": {"in": ids},
        "transaction_at": {"gte": start, "lt": end}})
    return sum(t.amount for t in txns)

async def get_user_points_earned_last_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet: return 0
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    types = await db.transaction_types.find_many(where={"is_credit": True})
    ids = [t.type_id for t in types]
    if not ids: return 0
    txns = await db.transactions.find_many(where={
        "wallet_id": wallet.wallet_id, "transaction_type_id": {"in": ids},
        "transaction_at": {"gte": start, "lt": end}})
    return sum(t.amount for t in txns)

async def get_user_total_rewards_redeemed(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet: return 0
    return await db.reward_history.count(where={"wallet_id": wallet.wallet_id})

async def get_user_rewards_redeemed_this_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet: return 0
    start, end = _month_range(_now())
    return await db.reward_history.count(where={
        "wallet_id": wallet.wallet_id, "granted_at": {"gte": start, "lt": end}})

async def get_user_rewards_redeemed_last_month(employee_id: str) -> int:
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet: return 0
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reward_history.count(where={
        "wallet_id": wallet.wallet_id, "granted_at": {"gte": start, "lt": end}})

async def get_user_total_reviews(employee_id: str) -> int:
    return await db.reviews.count(where={"receiver_id": employee_id})

async def get_user_reviews_this_month(employee_id: str) -> int:
    start, end = _month_range(_now())
    return await db.reviews.count(where={
        "receiver_id": employee_id, "review_at": {"gte": start, "lt": end}})

async def get_user_reviews_last_month(employee_id: str) -> int:
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reviews.count(where={
        "receiver_id": employee_id, "review_at": {"gte": start, "lt": end}})