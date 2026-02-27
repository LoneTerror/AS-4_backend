"""
conftest.py — shared fixtures, stubs, and helpers for all test files.

Stubs out src.prisma.client, src.recognition.dependencies, and
src.recognition.schemas so every test file can import the real modules
without a running Prisma / FastAPI stack.

FIXED:
- ReviewCreateRequest stub now includes category_id (required field added
  when categories moved from hardcoded enum to DB table)
- ReviewUpdateRequest stub now includes category_id (optional FK)
- make_review() now includes category_id, category_code, and points snapshot
  fields so _enrich_with_effective_points() can build a complete dict
- Added make_category_row(), make_role_row(), make_seasonal_row(),
  make_points_config_row() helpers for the new DB tables the points engine
  reads from during create/update
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
    "src.recognition.points_engine",
    "src.common",
    "src.common.middleware",
    "src.notifications",
    "src.notifications.service",
    "src.notifications.schemas",
]:
    sys.modules.setdefault(_path, types.ModuleType(_path))

# Stub NotificationService so service.py import does not fail
class _FakeNotificationService:
    def __init__(self, *args, **kwargs):
        pass
    async def send_review_notification(self, *args, **kwargs):
        pass
    async def send_notification(self, *args, **kwargs):
        pass

sys.modules["src.notifications.service"].NotificationService = _FakeNotificationService

# Stub NotificationType enum used by service.py
import enum as _enum
class _NotificationType(_enum.Enum):
    REVIEW_CREATED = "REVIEW_CREATED"
    REVIEW_UPDATED = "REVIEW_UPDATED"
    REVIEW_RECEIVED = "REVIEW_RECEIVED"
    GENERAL = "GENERAL"

sys.modules["src.notifications.schemas"].NotificationType = _NotificationType

# Load the REAL points_engine and wire its functions into the stub namespace.
# service.py does `from src.recognition.points_engine import calculate_points`
# so the stub module must hold the real callables — a MagicMock returning a
# float would cause `pts.raw_points` AttributeError in the service.
import importlib.util as _ilu, pathlib as _pl
_pe_path = _pl.Path(__file__).parent.parent / "points_engine.py"
_pe_spec = _ilu.spec_from_file_location("_real_points_engine", _pe_path)
_real_pe = _ilu.module_from_spec(_pe_spec)
_pe_spec.loader.exec_module(_real_pe)

_pe = sys.modules["src.recognition.points_engine"]
_pe.calculate_points = _real_pe.calculate_points
_pe.quarters_elapsed = _real_pe.quarters_elapsed
_pe.apply_decay      = _real_pe.apply_decay
_pe.PointsResult     = _real_pe.PointsResult

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
#
# FIX: Added category_id to both request stubs. The real ReviewCreateRequest
# requires category_id (UUID FK to review_categories) as of the DB-driven
# category refactor. Without it, service.create_review() blows up accessing
# payload.category_id before any DB call happens.
# ---------------------------------------------------------------------------
class ReviewCreateRequest(BaseModel):
    receiver_id: object
    rating: int
    comment: str
    category_id: object = None      # FIX: added — FK to review_categories table
    image_url: object = None
    video_url: object = None

class ReviewUpdateRequest(BaseModel):
    rating: int | None = None
    comment: str | None = None
    category_id: object = None      # FIX: added — optional FK; None means "no change"
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
    """
    Build a MagicMock that looks like a Prisma reviews row.

    FIX: Added category_id, category_code and points snapshot fields.
    _enrich_with_effective_points() calls vars(review) and then reads
    raw_points + review_at. Without these, every enrichment call returns
    effective_points=None and the returned dict is missing category fields.
    """
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
        # FIX: points snapshot + category fields expected by _enrich_with_effective_points
        category_id="cat-1",
        category_code="TEAMWORK",
        raw_points=8.0,
        category_multiplier=1.0,
        reviewer_weight=2.0,
        seasonal_multiplier=1.0,
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
# 6. New helpers for the points-engine DB tables
#    These are needed by service tests that exercise create_review /
#    update_review, because _resolve_points_inputs() now queries four tables.
# ---------------------------------------------------------------------------

def make_category_row(
    category_id="cat-1",
    category_code="TEAMWORK",
    multiplier=1.0,
    is_active=True,
):
    """Mimics a review_categories DB row."""
    row = MagicMock()
    row.category_id   = category_id
    row.category_code = category_code
    row.multiplier    = multiplier
    row.is_active     = is_active
    return row


def make_role_row(reviewer_weight=1.0):
    """Mimics a roles DB row."""
    row = MagicMock()
    row.reviewer_weight = reviewer_weight
    return row


def make_seasonal_row(multiplier=1.0):
    """Mimics a seasonal_multipliers DB row."""
    row = MagicMock()
    row.multiplier = multiplier
    return row


def make_points_config_row(config_value=0.9):
    """Mimics a points_config DB row (DECAY_RATE key)."""
    row = MagicMock()
    row.config_value = config_value
    return row


# ---------------------------------------------------------------------------
# 7. pytest fixtures
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