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
from typing import List, Optional
from uuid import UUID

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
_pe.PointsResult     = _real_pe.PointsResult

# ---------------------------------------------------------------------------
# 2. Fake database object — every test patches individual methods on this
# ---------------------------------------------------------------------------
fake_db = MagicMock()
async def fake_connect(): pass # Stub for the retry function

sys.modules["src.prisma.client"].db = fake_db
sys.modules["src.prisma.client"].connect_with_retry = fake_connect

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
    receiver_id: UUID
    rating: int
    comment: str
    category_ids: List[UUID]  # Updated: list of UUIDs
    image_url: Optional[str] = None
    video_url: Optional[str] = None

class ReviewUpdateRequest(BaseModel):
    rating: Optional[int] = None
    comment: Optional[str] = None
    category_ids: Optional[List[UUID]] = None # Updated: list of UUIDs
    image_url: Optional[str] = None
    video_url: Optional[str] = None

class ReviewCategoryCreateRequest(BaseModel):
    category_code: str
    category_name: str
    multiplier: float
    description: Optional[str] = None

class ReviewCategoryUpdateRequest(BaseModel):
    category_code: Optional[str] = None
    category_name: Optional[str] = None
    multiplier: Optional[float] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None

class ReviewCategoryTagResponse(BaseModel):
    category_id: UUID
    category_code: str
    multiplier_snapshot: float

class ReviewResponse(BaseModel):
    review_id: UUID
    reviewer_id: UUID
    receiver_id: UUID
    rating: int
    comment: str
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    status_id: UUID
    review_at: datetime
    created_at: datetime
    created_by: UUID
    updated_at: datetime
    updated_by: UUID
    # Multi-category fields
    category_tags: Optional[List[ReviewCategoryTagResponse]] = None
    category_ids: Optional[List[UUID]] = None
    category_codes: Optional[List[str]] = None
    raw_points: Optional[float] = None



_schemas = sys.modules["src.recognition.schemas"]
_schemas.ReviewCreateRequest = ReviewCreateRequest
_schemas.ReviewUpdateRequest = ReviewUpdateRequest
_schemas.ReviewCategoryCreateRequest = ReviewCategoryCreateRequest
_schemas.ReviewCategoryUpdateRequest = ReviewCategoryUpdateRequest
_schemas.ReviewResponse = ReviewResponse
_schemas.ReviewCategoryTagResponse = ReviewCategoryTagResponse

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
    Updated to support the multi-category tag relation.
    """
    uid = "990e8400-e29b-41d4-a716-446655440004"
    defaults = dict(
        review_id=uid,
        reviewer_id="880e8400-e29b-41d4-a716-446655440000",
        receiver_id="550e8400-e29b-41d4-a716-446655440000",
        rating=4,
        comment="Good job",
        image_url=None,
        video_url=None,
        status_id="aa0e8400-e29b-41d4-a716-446655440005",
        review_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        created_by="880e8400-e29b-41d4-a716-446655440000",
        updated_at=datetime.now(timezone.utc),
        updated_by="880e8400-e29b-41d4-a716-446655440000",
        raw_points=15.68,
        # Mock the relation for category tags
        category_tags=[
            make_category_tag_row(category_code="INNOVATION", multiplier=1.4),
            make_category_tag_row(category_code="TEAMWORK", multiplier=1.2)
        ]
    )
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    
    # Enable dict conversion for the service layer
    obj.__dict__.update(defaults)
    return obj

def make_category_tag_row(category_id=None, category_code="TAG", multiplier=1.0):
    """Mimics a row from the review_category_tags table."""
    row = MagicMock()
    row.category_id = category_id or "770e8400-e29b-41d4-a716-446655440001"
    row.category_code = category_code
    row.multiplier_snapshot = multiplier
    return row


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

@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset the global fake_db mock before and after every test."""
    fake_db.reset_mock()
    yield
    fake_db.reset_mock()