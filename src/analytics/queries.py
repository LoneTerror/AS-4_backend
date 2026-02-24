"""Prisma ORM queries for the dashboard summary endpoint."""
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from src.prisma.client import db


# ── Helpers ─────────────────────────────────────────────────────

def _month_range(dt: datetime):
    """Return (start_of_month, start_of_next_month) for the given datetime."""
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = start + relativedelta(months=1)
    return start, next_month


def _now():
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════
#  Employee
# ══════════════════════════════════════════════════════════════

async def get_employee_with_details(employee_id: str):
    """Fetch employee with designation and department names."""
    return await db.employees.find_unique(
        where={"employee_id": employee_id},
        include={
            "designations_employees_designation_idTodesignations": True,
            "departments_employees_department_idTodepartments": True,
        }
    )


# ══════════════════════════════════════════════════════════════
#  Recent reviews received
# ══════════════════════════════════════════════════════════════

async def get_recent_reviews(employee_id: str, limit: int = 5):
    """Fetch recent reviews received, with reviewer username."""
    return await db.reviews.find_many(
        where={"receiver_id": employee_id},
        include={
            "employees_reviews_reviewer_idToemployees": True,
        },
        order={"review_at": "desc"},
        take=limit,
    )


# ══════════════════════════════════════════════════════════════
#  Leaderboard
# ══════════════════════════════════════════════════════════════

async def get_leaderboard(limit: int = 10):
    """Top N employees ranked by total_earned_points."""
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


# ══════════════════════════════════════════════════════════════
#  1. Total Points (user's wallet total)
# ══════════════════════════════════════════════════════════════

async def get_user_total_points(employee_id: str) -> int:
    """Get the user's current total_earned_points from their wallet."""
    wallet = await db.wallets.find_first(
        where={"employee_id": employee_id}
    )
    return wallet.available_points if wallet else 0


async def get_user_points_earned_this_month(employee_id: str) -> int:
    """Sum of credit transactions for this user this month."""
    wallet = await db.wallets.find_first(
        where={"employee_id": employee_id}
    )
    if not wallet:
        return 0

    start, end = _month_range(_now())
    credit_types = await db.transaction_types.find_many(where={"is_credit": True})
    credit_type_ids = [t.type_id for t in credit_types]
    if not credit_type_ids:
        return 0

    txns = await db.transactions.find_many(
        where={
            "wallet_id": wallet.wallet_id,
            "transaction_type_id": {"in": credit_type_ids},
            "transaction_at": {"gte": start, "lt": end},
        }
    )
    return sum(t.amount for t in txns)


async def get_user_points_earned_last_month(employee_id: str) -> int:
    """Sum of credit transactions for this user last month."""
    wallet = await db.wallets.find_first(
        where={"employee_id": employee_id}
    )
    if not wallet:
        return 0

    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    credit_types = await db.transaction_types.find_many(where={"is_credit": True})
    credit_type_ids = [t.type_id for t in credit_types]
    if not credit_type_ids:
        return 0

    txns = await db.transactions.find_many(
        where={
            "wallet_id": wallet.wallet_id,
            "transaction_type_id": {"in": credit_type_ids},
            "transaction_at": {"gte": start, "lt": end},
        }
    )
    return sum(t.amount for t in txns)


# ══════════════════════════════════════════════════════════════
#  2. Rewards Redeemed — user-specific (lifetime + MoM)
# ══════════════════════════════════════════════════════════════

async def get_user_total_rewards_redeemed(employee_id: str) -> int:
    """Lifetime count of rewards redeemed by this user (via their wallet)."""
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    return await db.reward_history.count(
        where={"wallet_id": wallet.wallet_id}
    )


async def get_user_rewards_redeemed_this_month(employee_id: str) -> int:
    """Rewards redeemed by this user this month."""
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    start, end = _month_range(_now())
    return await db.reward_history.count(
        where={
            "wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start, "lt": end},
        }
    )


async def get_user_rewards_redeemed_last_month(employee_id: str) -> int:
    """Rewards redeemed by this user last month."""
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return 0
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reward_history.count(
        where={
            "wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start, "lt": end},
        }
    )


# ══════════════════════════════════════════════════════════════
#  3. Reviews Received — user-specific (lifetime + MoM)
# ══════════════════════════════════════════════════════════════

async def get_user_total_reviews(employee_id: str) -> int:
    """Lifetime count of reviews received by this user."""
    return await db.reviews.count(
        where={"receiver_id": employee_id}
    )


async def get_user_reviews_this_month(employee_id: str) -> int:
    """Reviews received by this user this month."""
    start, end = _month_range(_now())
    return await db.reviews.count(
        where={
            "receiver_id": employee_id,
            "review_at": {"gte": start, "lt": end},
        }
    )


async def get_user_reviews_last_month(employee_id: str) -> int:
    """Reviews received by this user last month."""
    last = _now() - relativedelta(months=1)
    start, end = _month_range(last)
    return await db.reviews.count(
        where={
            "receiver_id": employee_id,
            "review_at": {"gte": start, "lt": end},
        }
    )


# ══════════════════════════════════════════════════════════════
#  4. Active Users (current + month-over-month)
# ══════════════════════════════════════════════════════════════

async def get_active_users_count() -> int:
    """Count employees with an ACTIVE status."""
    active_status = await db.status_master.find_first(
        where={"status_code": "ACTIVE"}
    )
    if not active_status:
        return 0
    return await db.employees.count(
        where={"status_id": active_status.status_id}
    )


async def get_active_users_count_last_month() -> int:
    """Active employees who existed before start of this month."""
    active_status = await db.status_master.find_first(
        where={"status_code": "ACTIVE"}
    )
    if not active_status:
        return 0
    this_month_start, _ = _month_range(_now())
    return await db.employees.count(
        where={
            "status_id": active_status.status_id,
            "created_at": {"lt": this_month_start},
        }
    )
