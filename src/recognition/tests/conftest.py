"""
src/recognition/tests/conftest.py
───────────────────────────────────
Self-contained pytest config for the Recognition service.

Run from the project root:
    pytest src/recognition/tests/

No database, Redis, or auth service required.

Stub ordering (must be exact):
  1. Env vars
  2. sys.path  →  project root
  3. Third-party stubs (prisma, opentelemetry)
  4. src.* parent packages WITH __path__  (before sub-module stubs)
  5. src.* sub-module stubs
  6. DB mock  →  injected into src.prisma.client stub
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
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── 0. Env vars ───────────────────────────────────────────────────────────────
os.environ.setdefault("DATABASE_URL",          "postgresql://test:test@localhost/testdb")
os.environ.setdefault("SECRET_KEY",            "test-secret-key-32-chars-long!!!")
os.environ.setdefault("ALGORITHM",             "HS256")
os.environ.setdefault("AUTH_SERVICE_URL",      "http://auth-service/validate")
os.environ.setdefault("FRONTEND_CORS_ORIGINS", "http://localhost:3000")

# ── 1. sys.path ───────────────────────────────────────────────────────────────
# __file__ = <root>/src/recognition/tests/conftest.py  →  root is 3 levels up
_THIS_DIR     = os.path.dirname(os.path.abspath(__file__))      # src/recognition/tests/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))  # <root>/
# safety: also handle if tests/ is run from inside src/recognition/
if not os.path.isdir(os.path.join(_PROJECT_ROOT, "src")):
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(_THIS_DIR))  # one level less

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

_src_dir           = os.path.join(_PROJECT_ROOT, "src")
_common_dir        = os.path.join(_src_dir, "common")
_recognition_dir   = os.path.join(_src_dir, "recognition")
_prisma_src_dir    = os.path.join(_src_dir, "prisma")
_core_dir          = os.path.join(_src_dir, "core")
_notifications_dir = os.path.join(_src_dir, "notifications")
_digest_dir        = os.path.join(_src_dir, "digest")


# ── 2. Stub helpers ───────────────────────────────────────────────────────────

def _stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m

def _pkg(name: str, real_path: str | None = None) -> types.ModuleType:
    m = _stub(name)
    m.__path__    = [real_path] if real_path else []  # type: ignore[attr-defined]
    m.__package__ = name
    return m


# ── 3. Third-party stubs ──────────────────────────────────────────────────────

_pp = _pkg("prisma")
_pp.Prisma = MagicMock()                                                          # type: ignore
_pe = _stub("prisma.errors")
_pe.UniqueViolationError = type("UniqueViolationError", (Exception,), {})         # type: ignore

for _on in [
    "opentelemetry", "opentelemetry.trace",
    "opentelemetry.exporter", "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto", "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation", "opentelemetry.instrumentation.fastapi",
    "opentelemetry.sdk", "opentelemetry.sdk.resources",
    "opentelemetry.sdk.trace", "opentelemetry.sdk.trace.export",
]:
    _pkg(_on)

sys.modules["opentelemetry.trace"].set_tracer_provider = MagicMock()                                 # type: ignore
sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"].OTLPSpanExporter = MagicMock()  # type: ignore
sys.modules["opentelemetry.instrumentation.fastapi"].FastAPIInstrumentor = MagicMock()                # type: ignore
sys.modules["opentelemetry.sdk.resources"].Resource = MagicMock()                                    # type: ignore
sys.modules["opentelemetry.sdk.trace"].TracerProvider = MagicMock()                                  # type: ignore
sys.modules["opentelemetry.sdk.trace.export"].BatchSpanProcessor = MagicMock()                       # type: ignore


# ── 4. src.* parent packages (WITH __path__ so sub-imports resolve) ───────────
importlib.import_module("src")   # loads real src/__init__.py from disk
_src_mod = sys.modules["src"]

# Register each sub-package AND attach it as an attribute on the src module
# object. Without this, patch("src.common.X") fails on Python 3.10 because
# mock._importer traverses getattr(src, "common") — which is None if the
# real src package was imported before our stubs registered.
def _pkg_and_attach(name: str, real_path: str | None = None) -> types.ModuleType:
    m = _pkg(name, real_path)
    # attach the last component as an attribute on the parent module
    parts = name.split(".")
    if len(parts) == 2:                          # e.g. src.common → src
        setattr(_src_mod, parts[1], m)
    return m

_pkg_and_attach("src.common",        _common_dir)
_pkg_and_attach("src.recognition",   _recognition_dir)
_pkg_and_attach("src.prisma",        _prisma_src_dir)
_pkg_and_attach("src.core",          _core_dir)
_pkg_and_attach("src.notifications", _notifications_dir)
_pkg_and_attach("src.digest",        _digest_dir)


# ── 5. src.* sub-module stubs ─────────────────────────────────────────────────
# Each stub is also attached as an attribute on its parent package module so
# that patch("src.common.X") can traverse src → common → X via getattr().

_src_common      = sys.modules["src.common"]
_src_recognition = sys.modules["src.recognition"]

_cache = _stub("src.common.cache")
_cache.cache_get    = AsyncMock(return_value=None)  # type: ignore
_cache.cache_set    = AsyncMock(return_value=True)  # type: ignore
_cache.cache_delete = AsyncMock(return_value=True)  # type: ignore
_cache.TTL_MEDIUM   = 300                           # type: ignore
_cache.L1_MEDIUM    = 60                            # type: ignore
_src_common.cache = _cache                          # type: ignore[attr-defined]

_mid = _stub("src.common.middleware")
for _fn in ["generic_exception_handler", "http_exception_handler",
            "prisma_unique_violation_handler", "request_rate_limit_middleware",
            "validation_exception_handler"]:
    setattr(_mid, _fn, AsyncMock())
_src_common.middleware = _mid                       # type: ignore[attr-defined]

_reg = _stub("src.common.route_registry")
_reg.register_app_routes = AsyncMock()              # type: ignore
_src_common.route_registry = _reg                  # type: ignore[attr-defined]

_aud = _stub("src.common.audit")
_src_common.audit = _aud                           # type: ignore[attr-defined]

_ev = _stub("src.common.event_publisher")
_ev.publish = AsyncMock()                          # type: ignore
_src_common.event_publisher = _ev                  # type: ignore[attr-defined]

_src_core          = sys.modules["src.core"]
_src_notifications = sys.modules["src.notifications"]
_src_digest        = sys.modules["src.digest"]
_src_prisma        = sys.modules["src.prisma"]

_clog = _stub("src.core.logger")
_clog.logger = MagicMock()  # type: ignore
_src_core.logger = _clog    # type: ignore[attr-defined]

_email = _stub("src.notifications.email_sender")
_email.EmailSender = MagicMock()   # type: ignore
_email.SMTPConfig  = MagicMock()   # type: ignore
_src_notifications.email_sender = _email  # type: ignore[attr-defined]

_redisstub = _stub("src.notifications.redis_client")
_redisstub.connect_redis    = AsyncMock()  # type: ignore
_redisstub.disconnect_redis = AsyncMock()  # type: ignore
_src_notifications.redis_client = _redisstub  # type: ignore[attr-defined]

_dr = _stub("src.digest.router")
_dr.router = MagicMock()   # type: ignore
_src_digest.router = _dr   # type: ignore[attr-defined]

_dw = _stub("src.digest.worker")
_dw.digest_worker_loop = AsyncMock()  # type: ignore
_src_digest.worker = _dw              # type: ignore[attr-defined]


# ── 6. DB mock → src.prisma.client ────────────────────────────────────────────

_db_mock = MagicMock()
for _tbl in [
    "reviews", "review_categories", "review_category_tags",
    "employee_roles", "employees", "departments", "status_master",
    "route_permissions",
]:
    _tm = MagicMock()
    _tm.find_many   = AsyncMock(return_value=[])
    _tm.find_first  = AsyncMock(return_value=None)
    _tm.find_unique = AsyncMock(return_value=None)
    _tm.count       = AsyncMock(return_value=0)
    _tm.create      = AsyncMock(return_value=MagicMock())
    _tm.create_many = AsyncMock(return_value=MagicMock(count=0))
    _tm.update      = AsyncMock(return_value=MagicMock())
    _tm.delete      = AsyncMock(return_value=MagicMock())
    _tm.delete_many = AsyncMock(return_value=MagicMock())
    setattr(_db_mock, _tbl, _tm)

_pclient = _stub("src.prisma.client")
_pclient.db                 = _db_mock     # type: ignore
_pclient.connect_with_retry = AsyncMock()  # type: ignore
_pclient.set_audit_context  = AsyncMock()  # type: ignore
_src_prisma.client = _pclient              # type: ignore[attr-defined]


# ── 7. Force-load real src.common.dependencies ────────────────────────────────

_dep_spec = _ilu.spec_from_file_location(
    "src.common.dependencies",
    os.path.join(_common_dir, "dependencies.py"),
)
_dep_mod = _ilu.module_from_spec(_dep_spec)            # type: ignore[arg-type]
sys.modules["src.common.dependencies"] = _dep_mod
_dep_spec.loader.exec_module(_dep_mod)                 # type: ignore[union-attr]
_dep_mod.db = _db_mock                                 # type: ignore[attr-defined]
_src_common.dependencies = _dep_mod                    # type: ignore[attr-defined]


# ── 8. Data factories ─────────────────────────────────────────────────────────

def make_uuid() -> str:
    return str(uuid.uuid4())

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _fake_review(
    review_id:   str | None = None,
    reviewer_id: str | None = None,
    receiver_id: str | None = None,
    raw_points:  float = 2.6,
    tags: list | None = None,
) -> MagicMock:
    r = MagicMock()
    r.review_id   = review_id   or make_uuid()
    r.reviewer_id = reviewer_id or make_uuid()
    r.receiver_id = receiver_id or make_uuid()
    r.comment     = "Great work on the project!"
    r.image_url   = None
    r.video_url   = None
    r.status_id   = make_uuid()
    r.review_at   = utcnow()
    r.created_at  = utcnow()
    r.created_by  = r.reviewer_id
    r.updated_at  = utcnow()
    r.updated_by  = r.reviewer_id
    r.raw_points  = raw_points
    r.review_category_tags = tags if tags is not None else []
    return r

def _fake_category(
    category_id: str | None = None,
    code:        str   = "INNOVATION",
    name:        str   = "Innovation",
    multiplier:  float = 1.4,
    is_active:   bool  = True,
) -> MagicMock:
    c = MagicMock()
    c.category_id   = category_id or make_uuid()
    c.category_code = code
    c.category_name = name
    c.multiplier    = multiplier
    c.description   = "Recognises creative problem-solving"
    c.is_active     = is_active
    c.created_at    = utcnow()
    c.updated_at    = utcnow()
    c.created_by    = make_uuid()
    c.updated_by    = make_uuid()
    return c

def _fake_tag(
    category_id:         str | None = None,
    code_snapshot:       str   = "INNOVATION",
    multiplier_snapshot: float = 1.4,
) -> MagicMock:
    t = MagicMock()
    t.category_id            = category_id or make_uuid()
    t.category_code_snapshot = code_snapshot
    t.multiplier_snapshot    = multiplier_snapshot
    return t


# ── 9. Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def fake_review():
    return _fake_review

@pytest.fixture
def fake_category():
    return _fake_category

@pytest.fixture
def fake_tag():
    return _fake_tag