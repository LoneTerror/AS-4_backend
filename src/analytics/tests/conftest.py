"""
conftest.py — shared fixtures, stubs, and helpers for analytics test files.

Stubs out src.prisma.client, src.analytics.dependencies, and
src.analytics.schemas so every test file can import the real service
module without a running Prisma / FastAPI stack.
"""

import sys
import types
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import MagicMock
from pydantic import BaseModel
from typing import List

# ---------------------------------------------------------------------------
# 1. Stub the entire src.* namespace so real modules can be imported
# ---------------------------------------------------------------------------
_src = types.ModuleType("src")
sys.modules.setdefault("src", _src)

for _path in [
    "src.prisma",
    "src.prisma.client",
    "src.analytics",
    "src.analytics.dependencies",
    "src.analytics.queries",
    "src.analytics.schemas",
    "src.analytics.service",
]:
    sys.modules.setdefault(_path, types.ModuleType(_path))

# Load the REAL schemas so service.py can import the Pydantic models.
import importlib.util as _ilu, pathlib as _pl
_schemas_path = _pl.Path(__file__).parent.parent / "schemas.py"
_schemas_spec = _ilu.spec_from_file_location("_real_schemas", _schemas_path)
_real_schemas = _ilu.module_from_spec(_schemas_spec)
_schemas_spec.loader.exec_module(_real_schemas)

_schemas = sys.modules["src.analytics.schemas"]
_schemas.RecentReview     = _real_schemas.RecentReview
_schemas.LeaderboardEntry = _real_schemas.LeaderboardEntry
_schemas.MetricWithGrowth = _real_schemas.MetricWithGrowth
_schemas.PlatformStats    = _real_schemas.PlatformStats

# ---------------------------------------------------------------------------
# 2. Fake database object — every test patches individual methods on this
# ---------------------------------------------------------------------------
fake_db = MagicMock()
sys.modules["src.prisma.client"].db = fake_db

# ---------------------------------------------------------------------------
# 3. CurrentUser model (mirrors the real one in dependencies.py)
# ---------------------------------------------------------------------------
class CurrentUser(BaseModel):
    id: str
    email: str
    roles: List[str]
    department_id: str | None = None

sys.modules["src.analytics.dependencies"].CurrentUser = CurrentUser

# ---------------------------------------------------------------------------
# 4. Stub query functions so service.py can import them
#    Tests will patch these individually via unittest.mock.patch
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock

_queries = sys.modules["src.analytics.queries"]
_queries.get_recent_reviews                 = AsyncMock()
_queries.get_leaderboard                    = AsyncMock()
_queries.get_user_total_points              = AsyncMock()
_queries.get_user_points_earned_this_month  = AsyncMock()
_queries.get_user_points_earned_last_month  = AsyncMock()
_queries.get_user_total_rewards_redeemed    = AsyncMock()
_queries.get_user_rewards_redeemed_this_month = AsyncMock()
_queries.get_user_rewards_redeemed_last_month = AsyncMock()
_queries.get_user_total_reviews             = AsyncMock()
_queries.get_user_reviews_this_month        = AsyncMock()
_queries.get_user_reviews_last_month        = AsyncMock()
_queries.get_active_users_count             = AsyncMock()
_queries.get_active_users_count_last_month  = AsyncMock()


# ---------------------------------------------------------------------------
# 5. Reusable factory helpers (imported by every test file)
# ---------------------------------------------------------------------------

def make_user(user_id="user-1", roles=None, email="user@test.com", dept=None):
    return CurrentUser(
        id=user_id,
        email=email,
        roles=roles or ["EMPLOYEE"],
        department_id=dept,
    )


def make_reviewer(username="john.doe"):
    """Mimics the nested reviewer employee relation on a review row."""
    m = MagicMock()
    m.username = username
    return m


def make_raw_review(
    review_id=None,
    reviewer_username="john.doe",
    reviewer=None,
    rating=4,
    comment="Good job",
    review_at=None,
):
    """Build a MagicMock that looks like a Prisma reviews row from get_recent_reviews."""
    r = MagicMock()
    r.review_id = review_id or str(uuid4())
    r.rating = rating
    r.comment = comment
    r.review_at = review_at or datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc)
    if reviewer is not None:
        r.employees_reviews_reviewer_idToemployees = reviewer
    else:
        r.employees_reviews_reviewer_idToemployees = make_reviewer(reviewer_username)
    return r


def make_department(name="Engineering"):
    """Mimics a department relation object."""
    d = MagicMock()
    d.department_name = name
    return d


def make_employee(employee_id=None, username="alice", department_name="Engineering"):
    """Mimics an employee relation object with department."""
    e = MagicMock()
    e.employee_id = employee_id or str(uuid4())
    e.username = username
    e.departments_employees_department_idTodepartments = make_department(department_name)
    return e


def make_wallet_entry(
    employee_id=None,
    username="alice",
    department_name="Engineering",
    total_earned_points=100,
):
    """Build a MagicMock that looks like a Prisma wallets row from get_leaderboard."""
    w = MagicMock()
    w.employee_id = employee_id or str(uuid4())
    w.total_earned_points = total_earned_points
    emp = make_employee(
        employee_id=w.employee_id,
        username=username,
        department_name=department_name,
    )
    w.employees_wallets_employee_idToemployees = emp
    return w


# ---------------------------------------------------------------------------
# 6. pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def employee_user():
    return make_user(user_id="user-1", roles=["EMPLOYEE"])

@pytest.fixture
def hr_admin_user():
    return make_user(user_id="hr-1", roles=["HR_ADMIN"])
