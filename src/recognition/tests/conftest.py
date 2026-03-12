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
# 1. Surgically stub only the external dependencies (No root folder faking!)
# ---------------------------------------------------------------------------

# Fake the Prisma database client
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
_prisma_stub.db = MagicMock()
_prisma_stub.connect_with_retry = AsyncMock()
fake_db = _prisma_stub.db

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

# Ensure specific table methods are AsyncMocks (preserved from original)
fake_db.reviews.find_many = AsyncMock()
fake_db.reviews.find_unique = AsyncMock()
fake_db.reviews.create = AsyncMock()
fake_db.reviews.update = AsyncMock()
fake_db.reviews.delete = AsyncMock()
fake_db.reviews.count = AsyncMock()
fake_db.employees.find_unique = AsyncMock()
fake_db.employees.find_many = AsyncMock()
fake_db.status_master.find_first = AsyncMock()
fake_db.status_master.find_unique = AsyncMock()
fake_db.review_categories.find_unique = AsyncMock()
fake_db.review_categories.find_many = AsyncMock()
fake_db.review_category_tags.create_many = AsyncMock()
fake_db.review_category_tags.delete_many = AsyncMock()
fake_db.roles.find_first = AsyncMock()
fake_db.seasonal_multipliers.find_first = AsyncMock()
fake_db.wallets.find_unique = AsyncMock()
fake_db.transaction_types.find_unique = AsyncMock()
fake_db.transactions.create = AsyncMock()
fake_db.wallets.update_many = AsyncMock()

# Fake the Redis cache so it doesn't try to connect to a real Redis server
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

# Stub other external-ish things
_notif_redis_stub = types.ModuleType("src.notifications.redis_client")
sys.modules["src.notifications.redis_client"] = _notif_redis_stub
_notif_redis_stub.connect_redis = AsyncMock()
_notif_redis_stub.disconnect_redis = AsyncMock()

# For internal modules, we avoid replacing them if possible, 
# but if we must, we ensure they are not blank.
# However, many recognition tests depend on these being mocked.

def ensure_real_or_stub(mod_name):
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    try:
        import importlib
        return importlib.import_module(mod_name)
    except Exception:
        mod = types.ModuleType(mod_name)
        sys.modules[mod_name] = mod
        return mod

_notif_svc_stub = ensure_real_or_stub("src.notifications.service")
_wallet_svc_stub = ensure_real_or_stub("src.wallet.service")
_notif_email_stub = ensure_real_or_stub("src.notifications.email_sender")
_digest_router_stub = ensure_real_or_stub("src.digest.router")
_digest_worker_stub = ensure_real_or_stub("src.digest.worker")
_notif_schemas_stub = ensure_real_or_stub("src.notifications.schemas")

# Stub NotificationService — service.py calls _notif.create_notification()
class _FakeNotificationService:
    def __init__(self, *args, **kwargs):
        pass
    async def create_notification(self, *args, **kwargs):
        pass

_notif_svc_stub.NotificationService = _FakeNotificationService

# Stub wallet functions (imported inline inside service.py)
async def _fake_credit_wallet(*args, **kwargs):
    return {"credited_points": 0, "new_balance": 0}

async def _fake_adjust_wallet(*args, **kwargs):
    return {"new_balance": 0}

_wallet_svc_stub.credit_wallet_from_review = _fake_credit_wallet
_wallet_svc_stub.adjust_wallet_for_review_update = _fake_adjust_wallet

# Stub EmailSender / SMTPConfig for main.py import
class _FakeSMTPConfig:
    @classmethod
    def from_env(cls):
        return cls()

class _FakeEmailSender:
    def __init__(self, *args, **kwargs):
        pass

_notif_email_stub.SMTPConfig  = _FakeSMTPConfig
_notif_email_stub.EmailSender = _FakeEmailSender

# Stub digest router + worker
from fastapi import APIRouter as _APIRouter
_digest_router_stub.router = _APIRouter()

async def _fake_digest_worker(*args, **kwargs):
    pass

_digest_worker_stub.digest_worker_loop = _fake_digest_worker

# Stub NotificationType enum
import enum as _enum

class _NotificationType(_enum.Enum):
    REVIEW = "REVIEW"
    REWARD = "REWARD"
    SYSTEM = "SYSTEM"

_notif_schemas_stub.NotificationType = _NotificationType

# ---------------------------------------------------------------------------
# 2. Load REAL points_engine
# ---------------------------------------------------------------------------
import importlib.util as _ilu, pathlib as _pl

_pe_path = _pl.Path(__file__).parent.parent / "points_engine.py"
_pe_spec = _ilu.spec_from_file_location("_real_points_engine", _pe_path)
_real_pe = _ilu.module_from_spec(_pe_spec)
_pe_spec.loader.exec_module(_real_pe)

_pe_stub = ensure_real_or_stub("src.recognition.points_engine")
_pe_stub.calculate_points = _real_pe.calculate_points
_pe_stub.PointsResult     = _real_pe.PointsResult

# ---------------------------------------------------------------------------
# 3. CurrentUser model
# ---------------------------------------------------------------------------
class CurrentUser(BaseModel):
    id:            str
    email:         str
    roles:         List[str]
    department_id: Optional[str] = None

_deps_stub = ensure_real_or_stub("src.recognition.dependencies")
_deps_stub.CurrentUser = CurrentUser

# ---------------------------------------------------------------------------
# 4. Schema stubs — use category_ids (plural List) to match real schemas.py
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

_schemas_stub = ensure_real_or_stub("src.recognition.schemas")
_schemas_stub.ReviewCreateRequest = ReviewCreateRequest
_schemas_stub.ReviewUpdateRequest = ReviewUpdateRequest

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
