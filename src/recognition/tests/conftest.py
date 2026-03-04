"""
conftest.py — shared fixtures, stubs, and helpers for all test files.

FIXED:
- ReviewCreateRequest/UpdateRequest stubs now use category_ids (plural List)
  matching the real schema. The old stubs used category_id (singular UUID)
  which caused `for cid in payload.category_ids` in service.py to fail.
- Removed stubs for quarters_elapsed / apply_decay — these functions do not
  exist in points_engine.py and caused AttributeError on module load.
- Added src.wallet, src.wallet.service stubs so service.py inline imports
  (credit_wallet_from_review, adjust_wallet_for_review_update) don't crash.
- Fixed _FakeNotificationService to expose create_notification() — the method
  service.py actually calls on _notif.
- make_review() now sets review_category_tags=[] (plain list, not MagicMock)
  so _build_review_dict() can iterate over it without errors.
- Added src.digest / src.notifications.email_sender stubs for main.py tests.
"""

import sys
import types
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel
from typing import List, Optional

# ---------------------------------------------------------------------------
# 1. Stub the entire src.* namespace
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
    "src.notifications.email_sender",
    "src.wallet",
    "src.wallet.service",
    "src.digest",
    "src.digest.router",
    "src.digest.worker",
]:
    sys.modules.setdefault(_path, types.ModuleType(_path))

# Stub NotificationService — service.py calls _notif.create_notification()
class _FakeNotificationService:
    def __init__(self, *args, **kwargs):
        pass
    async def create_notification(self, *args, **kwargs):
        pass

sys.modules["src.notifications.service"].NotificationService = _FakeNotificationService

# Stub wallet functions (imported inline inside service.py)
async def _fake_credit_wallet(*args, **kwargs):
    return {"credited_points": 0, "new_balance": 0}

async def _fake_adjust_wallet(*args, **kwargs):
    return {"new_balance": 0}

sys.modules["src.wallet.service"].credit_wallet_from_review = _fake_credit_wallet
sys.modules["src.wallet.service"].adjust_wallet_for_review_update = _fake_adjust_wallet

# Stub EmailSender / SMTPConfig for main.py import
class _FakeSMTPConfig:
    @classmethod
    def from_env(cls):
        return cls()

class _FakeEmailSender:
    def __init__(self, *args, **kwargs):
        pass

sys.modules["src.notifications.email_sender"].SMTPConfig  = _FakeSMTPConfig
sys.modules["src.notifications.email_sender"].EmailSender = _FakeEmailSender

# Stub digest router + worker
from fastapi import APIRouter as _APIRouter
sys.modules["src.digest.router"].router = _APIRouter()

async def _fake_digest_worker(*args, **kwargs):
    pass

sys.modules["src.digest.worker"].digest_worker_loop = _fake_digest_worker

# Stub NotificationType enum
import enum as _enum

class _NotificationType(_enum.Enum):
    REVIEW = "REVIEW"
    REWARD = "REWARD"
    SYSTEM = "SYSTEM"

sys.modules["src.notifications.schemas"].NotificationType = _NotificationType

# ---------------------------------------------------------------------------
# 2. Load REAL points_engine
#    points_engine.py only exports calculate_points + PointsResult.
#    quarters_elapsed and apply_decay do NOT exist — do not stub them.
# ---------------------------------------------------------------------------
import importlib.util as _ilu, pathlib as _pl

_pe_path = _pl.Path(__file__).parent.parent / "points_engine.py"
_pe_spec = _ilu.spec_from_file_location("_real_points_engine", _pe_path)
_real_pe = _ilu.module_from_spec(_pe_spec)
_pe_spec.loader.exec_module(_real_pe)

_pe = sys.modules["src.recognition.points_engine"]
_pe.calculate_points = _real_pe.calculate_points
_pe.PointsResult     = _real_pe.PointsResult

# ---------------------------------------------------------------------------
# 3. Fake database object
# ---------------------------------------------------------------------------
fake_db = MagicMock()
sys.modules["src.prisma.client"].db             = fake_db
sys.modules["src.prisma.client"].connect_with_retry = AsyncMock()

# ---------------------------------------------------------------------------
# 4. CurrentUser model
# ---------------------------------------------------------------------------
class CurrentUser(BaseModel):
    id:            str
    email:         str
    roles:         List[str]
    department_id: Optional[str] = None

sys.modules["src.recognition.dependencies"].CurrentUser = CurrentUser

# ---------------------------------------------------------------------------
# 5. Schema stubs — use category_ids (plural List) to match real schemas.py
# ---------------------------------------------------------------------------
class ReviewCreateRequest(BaseModel):
    receiver_id:  object
    rating:       int
    comment:      str
    category_ids: List[object]           # FIXED: plural list
    image_url:    object = None
    video_url:    object = None

class ReviewUpdateRequest(BaseModel):
    rating:       Optional[int]           = None
    comment:      Optional[str]           = None
    category_ids: Optional[List[object]]  = None  # FIXED: plural, optional
    image_url:    object                  = None
    video_url:    object                  = None

sys.modules["src.recognition.schemas"].ReviewCreateRequest = ReviewCreateRequest
sys.modules["src.recognition.schemas"].ReviewUpdateRequest = ReviewUpdateRequest

# ---------------------------------------------------------------------------
# 6. Factory helpers
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
    Build a MagicMock resembling a Prisma reviews row.

    FIXED: review_category_tags is a plain empty list so _build_review_dict()
    can iterate it without hitting MagicMock iteration errors.
    raw_points is a plain float so float() calls in the service don't fail.
    __dict__ is populated so vars(review) works in _build_review_dict().
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
        updated_by="user-1",
        raw_points=8.0,
        review_category_tags=[],  # FIXED: plain list, not MagicMock
    )
    defaults.update(kwargs)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    # _build_review_dict calls vars(review) — populate __dict__ so it works
    obj.__dict__.update({k: v for k, v in defaults.items()
                         if not k.startswith("_")})
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


def make_category_row(
    category_id="cat-1",
    category_code="TEAMWORK",
    multiplier=1.0,
    is_active=True,
):
    row = MagicMock()
    row.category_id   = category_id
    row.category_code = category_code
    row.multiplier    = multiplier
    row.is_active     = is_active
    return row


def make_role_row(reviewer_weight=1.0):
    row = MagicMock()
    row.reviewer_weight = reviewer_weight
    return row


def make_seasonal_row(multiplier=1.0):
    row = MagicMock()
    row.multiplier = multiplier
    return row


def make_points_config_row(config_value=0.9):
    """
    Kept for backward compatibility. The current service.py no longer queries
    points_config, but this helper is still imported by some test files.
    """
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
    return fake_db
