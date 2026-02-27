"""
conftest.py — shared fixtures, stubs, and helpers for all test files.

Stubs out src.prisma.client, src.recognition.dependencies, and
src.recognition.schemas so every test file can import the real modules
without a running Prisma / FastAPI stack.
"""

import sys
import types
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
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
    "src.recognition",
    "src.recognition.dependencies",
    "src.recognition.schemas",
    "src.common",
    "src.common.middleware",
]:
    sys.modules.setdefault(_path, types.ModuleType(_path))

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

sys.modules["src.recognition.dependencies"].CurrentUser = CurrentUser

# ---------------------------------------------------------------------------
# 4. Lightweight schema stubs (enough for service.py to import)
# ---------------------------------------------------------------------------
class ReviewCreateRequest(BaseModel):
    receiver_id: object
    rating: int
    comment: str
    image_url: object = None
    video_url: object = None

class ReviewUpdateRequest(BaseModel):
    rating: int | None = None
    comment: str | None = None
    image_url: object = None
    video_url: object = None

sys.modules["src.recognition.schemas"].ReviewCreateRequest = ReviewCreateRequest
sys.modules["src.recognition.schemas"].ReviewUpdateRequest = ReviewUpdateRequest

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


def make_review(**kwargs):
    defaults = dict(
        review_id="rev-1",
        reviewer_id="user-1",
        receiver_id="user-2",
        rating=4,
        comment="Good job",
        image_url=None,
        video_url=None,
        status_id="status-1",
        review_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        created_by="user-1",
        updated_at=datetime.now(timezone.utc),
        updated_by="user-1",
    )
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def make_active_employee():
    status = MagicMock()
    status.status_code = "ACTIVE"
    emp = MagicMock()
    emp.status_master_employees_status_idTostatus_master = status
    return emp


def make_inactive_employee():
    status = MagicMock()
    status.status_code = "INACTIVE"
    emp = MagicMock()
    emp.status_master_employees_status_idTostatus_master = status
    return emp


def make_employee_no_status():
    emp = MagicMock()
    emp.status_master_employees_status_idTostatus_master = None
    return emp


def make_review_status(status_id="status-active"):
    s = MagicMock()
    s.status_id = status_id
    return s


# ---------------------------------------------------------------------------
# 6. pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def employee_user():
    return make_user(user_id="user-1", roles=["EMPLOYEE"])

@pytest.fixture
def manager_user():
    return make_user(user_id="mgr-1", roles=["MANAGER"])

@pytest.fixture
def hr_admin_user():
    return make_user(user_id="hr-1", roles=["HR_ADMIN"])

@pytest.fixture
def super_admin_user():
    return make_user(user_id="sadmin", roles=["SUPER_ADMIN"])

@pytest.fixture
def sample_review():
    return make_review()

@pytest.fixture
def db_patch():
    """Returns the fake_db object for direct attribute inspection."""
    return fake_db
