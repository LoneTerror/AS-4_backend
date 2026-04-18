"""
src/roles/tests/conftest.py
────────────────────────────
Self-contained pytest config for the Roles & Permissions service.

Run from the project root:
    pytest src/roles/tests/

No database, Redis, or external service required.

Stub ordering:
  1. Env vars
  2. sys.path → project root
  3. Third-party stubs (prisma, opentelemetry)
  4. src.* parent packages WITH __path__
  5. src.* sub-module stubs
  6. DB mock → src.prisma.client
  7. Force-load real src.common.dependencies
  8. Data factories + fixtures
"""
from __future__ import annotations

import importlib
import importlib.util as _ilu
import os
import sys
import types
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 0. Env vars ───────────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",          "postgresql://test:test@localhost/testdb")
os.environ.setdefault("SECRET_KEY",            "test-secret-key-32-chars-long!!!")
os.environ.setdefault("ALGORITHM",             "HS256")
os.environ.setdefault("AUTH_SERVICE_URL",      "http://auth-service/validate")
os.environ.setdefault("FRONTEND_CORS_ORIGINS", "http://localhost:3000")
os.environ.setdefault("REDIS_URL",             "redis://localhost:6379")

# ── 1. sys.path ───────────────────────────────────────────────────────────────
_THIS_DIR     = os.path.dirname(os.path.abspath(__file__))          # src/roles/tests/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))
if not os.path.isdir(os.path.join(_PROJECT_ROOT, "src")):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_src_dir           = os.path.join(_PROJECT_ROOT, "src")
_common_dir        = os.path.join(_src_dir, "common")
_roles_dir         = os.path.join(_src_dir, "roles")
_prisma_src_dir    = os.path.join(_src_dir, "prisma")
_core_dir          = os.path.join(_src_dir, "core")
_notifications_dir = os.path.join(_src_dir, "notifications")

# ── 2. Stub helpers ───────────────────────────────────────────────────────────
def _stub(name):
    m = types.ModuleType(name); sys.modules[name] = m; return m
def _pkg(name, real_path=None):
    m = _stub(name); m.__path__ = [real_path] if real_path else []; m.__package__ = name; return m

# ── 3. Third-party stubs ──────────────────────────────────────────────────────
_pp = _pkg("prisma"); _pp.Prisma = MagicMock()
_pe = _stub("prisma.errors"); _pe.UniqueViolationError = type("UniqueViolationError",(Exception,),{})

for _on in [
    "opentelemetry","opentelemetry.trace",
    "opentelemetry.exporter","opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto","opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation","opentelemetry.instrumentation.fastapi",
    "opentelemetry.sdk","opentelemetry.sdk.resources",
    "opentelemetry.sdk.trace","opentelemetry.sdk.trace.export",
]: _pkg(_on)

sys.modules["opentelemetry.trace"].set_tracer_provider = MagicMock()
sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"].OTLPSpanExporter = MagicMock()
sys.modules["opentelemetry.instrumentation.fastapi"].FastAPIInstrumentor = MagicMock()
sys.modules["opentelemetry.sdk.resources"].Resource = MagicMock()
sys.modules["opentelemetry.sdk.trace"].TracerProvider = MagicMock()
sys.modules["opentelemetry.sdk.trace.export"].BatchSpanProcessor = MagicMock()

# ── 4. src.* parent packages ──────────────────────────────────────────────────
importlib.import_module("src")
_src_mod = sys.modules["src"]

def _pkg_and_attach(name, real_path=None):
    m = _pkg(name, real_path)
    parts = name.split(".")
    if len(parts) == 2: setattr(_src_mod, parts[1], m)
    return m

_pkg_and_attach("src.common",        _common_dir)
_pkg_and_attach("src.roles",         _roles_dir)
_pkg_and_attach("src.prisma",        _prisma_src_dir)
_pkg_and_attach("src.core",          _core_dir)
_pkg_and_attach("src.notifications", _notifications_dir)

# ── 5. Sub-module stubs ───────────────────────────────────────────────────────
_src_common = sys.modules["src.common"]
_src_core   = sys.modules["src.core"]
_src_prisma = sys.modules["src.prisma"]
_src_notif  = sys.modules["src.notifications"]

# src.common.cache — service imports TTL_* and L1_* constants as well
_cache = _stub("src.common.cache")
_cache.cache_get          = AsyncMock(return_value=None)
_cache.cache_set          = AsyncMock(return_value=True)
_cache.cache_delete       = AsyncMock(return_value=True)
_cache.invalidate_pattern = AsyncMock(return_value=True)
_cache.TTL_VOLATILE   = 60;    _cache.L1_VOLATILE   = 10
_cache.TTL_MEDIUM     = 300;   _cache.L1_MEDIUM     = 60
_cache.TTL_PERMANENT  = 86400; _cache.L1_PERMANENT  = 3600
_src_common.cache = _cache

# src.common.middleware
_mid = _stub("src.common.middleware")
for _fn in ["generic_exception_handler","http_exception_handler",
            "prisma_unique_violation_handler","request_rate_limit_middleware",
            "validation_exception_handler"]:
    setattr(_mid, _fn, AsyncMock())
_src_common.middleware = _mid

# src.common.route_registry
_reg = _stub("src.common.route_registry"); _reg.register_app_routes = AsyncMock()
_src_common.route_registry = _reg

# src.common.audit
_aud = _stub("src.common.audit"); _aud.audit = AsyncMock()
@asynccontextmanager
async def _fake_audit_ctx(**kwargs): yield
_aud.audit_ctx = _fake_audit_ctx
_src_common.audit = _aud

# src.common.event_publisher
_ev = _stub("src.common.event_publisher"); _ev.publish = AsyncMock()
_src_common.event_publisher = _ev

# src.core.logger
_clog = _stub("src.core.logger"); _clog.logger = MagicMock(); _src_core.logger = _clog

# src.notifications stubs
_redisstub = _stub("src.notifications.redis_client")
_redisstub.connect_redis = AsyncMock(); _redisstub.disconnect_redis = AsyncMock()
_src_notif.redis_client = _redisstub

# ── 6. DB mock → src.prisma.client ────────────────────────────────────────────
_db_mock = MagicMock()
for _tbl in ["roles","employee_roles","route_permissions","employees","route_permissions"]:
    _tm = MagicMock()
    _tm.find_many   = AsyncMock(return_value=[])
    _tm.find_first  = AsyncMock(return_value=None)
    _tm.find_unique = AsyncMock(return_value=None)
    _tm.count       = AsyncMock(return_value=0)
    _tm.create      = AsyncMock(return_value=MagicMock())
    _tm.create_many = AsyncMock(return_value=MagicMock(count=0))
    _tm.update      = AsyncMock(return_value=MagicMock())
    _tm.update_many = AsyncMock(return_value=MagicMock())
    _tm.delete      = AsyncMock(return_value=MagicMock())
    _tm.delete_many = AsyncMock(return_value=MagicMock())
    setattr(_db_mock, _tbl, _tm)

_pclient = _stub("src.prisma.client")
_pclient.db = _db_mock; _pclient.connect_with_retry = AsyncMock()
_src_prisma.client = _pclient

# ── 7. Force-load real src.common.dependencies ────────────────────────────────
_dep_spec = _ilu.spec_from_file_location(
    "src.common.dependencies", os.path.join(_common_dir, "dependencies.py")
)
_dep_mod = _ilu.module_from_spec(_dep_spec)
sys.modules["src.common.dependencies"] = _dep_mod
try:
    _dep_spec.loader.exec_module(_dep_mod); _dep_mod.db = _db_mock
except Exception:
    _dep_mod = _stub("src.common.dependencies")
    from pydantic import BaseModel
    from typing import List, Optional as _Opt
    class CurrentUser(BaseModel):
        id: str; email: str; roles: List[str]; department_id: _Opt[str] = None
    _dep_mod.CurrentUser            = CurrentUser
    _dep_mod.check_route_permission = AsyncMock()
    _dep_mod.get_current_user       = AsyncMock()
    _dep_mod.register_public_paths  = MagicMock()
    _dep_mod._is_public             = MagicMock(return_value=False)
    _dep_mod.db                     = _db_mock
    sys.modules["src.common.dependencies"] = _dep_mod
_src_common.dependencies = _dep_mod

# ── 8. Data factories ──────────────────────────────────────────────────────────
def make_uuid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _fake_role(
    role_id=None, role_code="EMPLOYEE", role_name="Employee",
    description=None, reviewer_weight=1.0,
):
    r = MagicMock()
    r.role_id          = role_id or make_uuid()
    r.role_code        = role_code
    r.role_name        = role_name
    r.description      = description
    r.reviewer_weight  = reviewer_weight
    r.created_at       = utcnow()
    r.updated_at       = utcnow()
    r.created_by       = make_uuid()
    r.updated_by       = make_uuid()
    r.model_dump.return_value = {
        "role_id": r.role_id, "role_code": r.role_code,
        "role_name": r.role_name, "description": r.description,
    }
    return r

def _fake_employee_stub(employee_id=None, username="john.doe", email="john@example.com"):
    e = MagicMock()
    e.employee_id = employee_id or make_uuid()
    e.username    = username
    e.email       = email
    return e

def _fake_employee_role(
    employee_role_id=None, employee_id=None, role_id=None,
    is_active=True, assigned_at=None,
    employee=None, role=None,
):
    er = MagicMock()
    er.employee_role_id = employee_role_id or make_uuid()
    er.employee_id      = employee_id      or make_uuid()
    er.role_id          = role_id          or make_uuid()
    er.is_active        = is_active
    er.assigned_at      = assigned_at or utcnow()
    er.employees_employee_roles_employee_idToemployees = employee or _fake_employee_stub()
    er.roles            = role or _fake_role()
    return er

def _fake_route_permission(
    perm_id=None, route_key="GET:/aabhar/v1/roles/list", role_id=None,
    is_active=True, title="List Roles", role=None,
):
    rp = MagicMock()
    rp.id        = perm_id  or make_uuid()
    rp.route_key = route_key
    rp.role_id   = role_id  or make_uuid()
    rp.is_active = is_active
    rp.title     = title
    rp.roles     = role or _fake_role()
    rp.model_dump.return_value = {
        "id": rp.id, "route_key": rp.route_key,
        "role_id": rp.role_id, "is_active": rp.is_active,
    }
    return rp

def _current_user(user_id=None, roles=None):
    from src.common.dependencies import CurrentUser
    return CurrentUser(
        id=user_id or make_uuid(),
        email="admin@test.com",
        roles=roles or ["SUPER_ADMIN"],
    )

# ── 9. Fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def fake_role(): return _fake_role
@pytest.fixture
def fake_employee_stub(): return _fake_employee_stub
@pytest.fixture
def fake_employee_role(): return _fake_employee_role
@pytest.fixture
def fake_route_permission(): return _fake_route_permission
@pytest.fixture
def current_user(): return _current_user()
@pytest.fixture
def db(): return _db_mock
