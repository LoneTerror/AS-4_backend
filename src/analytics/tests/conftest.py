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
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel
from typing import List

import src.analytics.schemas as _schemas

# 1. Safely stub ONLY the database and cache
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
_prisma_stub.db = MagicMock()

# Ensure common DB methods are AsyncMocks
_prisma_stub.db.find_many = AsyncMock()
_prisma_stub.db.find_unique = AsyncMock()
_prisma_stub.db.find_first = AsyncMock()
_prisma_stub.db.create = AsyncMock()
_prisma_stub.db.update = AsyncMock()
_prisma_stub.db.delete = AsyncMock()
_prisma_stub.db.count = AsyncMock()
_prisma_stub.db.update_many = AsyncMock()
_prisma_stub.db.delete_many = AsyncMock()
_prisma_stub.db.tx = AsyncMock()
_prisma_stub.connect_with_retry = AsyncMock()

# Keep specific table mocks if they existed
_prisma_stub.db.reviews.find_many = AsyncMock()
_prisma_stub.db.wallets.find_many = AsyncMock()
_prisma_stub.db.employees.find_unique = AsyncMock()

_cache_stub = types.ModuleType("src.common.cache")
sys.modules["src.common.cache"] = _cache_stub
_cache_stub.cache_get = AsyncMock(return_value=None)
_cache_stub.cache_set = AsyncMock()
_cache_stub.cache_delete = AsyncMock()
_cache_stub.invalidate_pattern = AsyncMock()

# TTL and L1 constants
_cache_stub.TTL_VOLATILE = 60
_cache_stub.L1_VOLATILE = 30
_cache_stub.TTL_SHORT = 300
_cache_stub.L1_SHORT = 60
_cache_stub.TTL_MEDIUM = 3600
_cache_stub.L1_MEDIUM = 300
_cache_stub.TTL_PERMANENT = 86400
_cache_stub.L1_PERMANENT = 3600

sys.modules["src.analytics.dependencies"] = types.ModuleType("src.analytics.dependencies")

class CurrentUser(BaseModel):
    id: str
    email: str
    roles: List[str]
    department_id: str | None = None

sys.modules["src.analytics.dependencies"].CurrentUser = CurrentUser

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
    comment="Good job",
    review_at=None,
    tags=None,
):
    """Build a MagicMock that looks like a Prisma reviews row from get_recent_reviews."""
    r = MagicMock()
    r.review_id = review_id or str(uuid4())
    r.comment = comment
    r.review_at = review_at or datetime(2026, 2, 15, 10, 0, tzinfo=timezone.utc)
    
    # Mock tags
    r.review_category_tags = []
    if tags:
        for t_code in tags:
            t = MagicMock()
            t.category_code_snapshot = t_code
            r.review_category_tags.append(t)

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
