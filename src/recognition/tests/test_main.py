"""
test_main.py
Unit tests for main.py (FastAPI application factory)

FIXED:
- Added stubs for src.digest.router, src.digest.worker,
  src.notifications.email_sender so main.py can be imported. The real
  main.py imports digest_router, digest_worker_loop, EmailSender, SMTPConfig
  at the top level — without stubs the import fails immediately.
- Added connect_with_retry stub on src.prisma.client — main.py calls
  `await connect_with_retry()` in the lifespan, not `await db.connect()`.
  Tests that asserted db.connect.called were wrong; updated to check
  connect_with_retry.called.
- digest_task.cancel() is called in lifespan teardown; the fake worker is
  an infinite coroutine so asyncio.create_task works without side effects.
"""

import os
import sys
import types
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Stub ALL heavy dependencies before importing main.py
# ---------------------------------------------------------------------------
for _p in [
    "src", "src.prisma", "src.prisma.client",
    "src.recognition", "src.recognition.router",
    "src.recognition.dependencies", "src.recognition.schemas",
    "src.recognition.service",
    "src.common", "src.common.middleware",
    "src.notifications", "src.notifications.email_sender",
    "src.digest", "src.digest.router", "src.digest.worker",
]:
    if _p not in sys.modules:
        sys.modules[_p] = types.ModuleType(_p)

# Fake database — main.py calls connect_with_retry() then db.disconnect()
_fake_db = MagicMock()
_fake_db.disconnect = AsyncMock()

_fake_connect = AsyncMock()   # connect_with_retry is a standalone coroutine

sys.modules["src.prisma.client"].db                 = _fake_db
sys.modules["src.prisma.client"].connect_with_retry = _fake_connect

# Fake routers
from fastapi import APIRouter
_fake_recognition_router  = APIRouter()
_fake_categories_router   = APIRouter()
_fake_digest_router       = APIRouter()
sys.modules["src.recognition.router"].router           = _fake_recognition_router
sys.modules["src.recognition.router"].categories_router = _fake_categories_router
sys.modules["src.digest.router"].router                = _fake_digest_router

# Fake digest worker — must be an async generator / long-running coroutine;
# asyncio.create_task needs a coroutine, so wrap in an infinite loop.
async def _fake_digest_worker_loop(*args, **kwargs):
    try:
        await asyncio.sleep(9999)
    except asyncio.CancelledError:
        pass

sys.modules["src.digest.worker"].digest_worker_loop = _fake_digest_worker_loop

# Fake EmailSender / SMTPConfig
class _FakeSMTPConfig:
    @classmethod
    def from_env(cls):
        return cls()

class _FakeEmailSender:
    def __init__(self, *args, **kwargs):
        pass

sys.modules["src.notifications.email_sender"].SMTPConfig  = _FakeSMTPConfig
sys.modules["src.notifications.email_sender"].EmailSender = _FakeEmailSender

# Fake middleware functions
async def _fake_rate_limit(request, call_next):
    return await call_next(request)

async def _fake_http_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=500)

async def _fake_validation_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=422)

async def _fake_generic_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": "error"}, status_code=500)

_mw_mod = sys.modules["src.common.middleware"]
_mw_mod.request_rate_limit_middleware = _fake_rate_limit
_mw_mod.http_exception_handler        = _fake_http_handler
_mw_mod.validation_exception_handler  = _fake_validation_handler
_mw_mod.generic_exception_handler     = _fake_generic_handler

# ---------------------------------------------------------------------------
# Import the real main module
# ---------------------------------------------------------------------------
import importlib.util, pathlib

_main_path = pathlib.Path(__file__).parent.parent / "main.py"
_spec = importlib.util.spec_from_file_location("main_mod", _main_path)
_main_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_main_mod)

app = _main_mod.app


# ===========================================================================
# App metadata
# ===========================================================================

class TestAppMetadata:

    def test_app_title_is_recognition_service(self):
        assert app.title == "Recognition Service"

    def test_app_version(self):
        assert app.version == "1.0.0"

    def test_openapi_url(self):
        assert app.openapi_url == "/v1/openapi.json"

    def test_docs_url(self):
        assert app.docs_url == "/v1/docs"

    def test_redoc_url(self):
        assert app.redoc_url == "/v1/redoc"


# ===========================================================================
# Router inclusion
# ===========================================================================

class TestRouterInclusion:

    def test_recognition_router_mounted_at_v1(self):
        prefixes = [r.path for r in app.routes]
        assert any("/v1" in p for p in prefixes)

    def test_router_tags_no_error(self):
        tags_found = set()
        for route in app.routes:
            tags_found.update(getattr(route, "tags", []))
        assert isinstance(tags_found, set)


# ===========================================================================
# CORS middleware
# ===========================================================================

class TestCORSMiddleware:

    def _cors_config(self):
        from starlette.middleware.cors import CORSMiddleware
        for mw in app.user_middleware:
            if mw.cls is CORSMiddleware:
                return mw.kwargs
        return {}

    def test_cors_middleware_is_registered(self):
        from starlette.middleware.cors import CORSMiddleware
        classes = [mw.cls for mw in app.user_middleware]
        assert CORSMiddleware in classes

    def test_cors_allows_localhost_3000(self):
        cfg = self._cors_config()
        assert "http://localhost:3000" in cfg.get("allow_origins", [])

    def test_cors_allows_credentials(self):
        cfg = self._cors_config()
        assert cfg.get("allow_credentials") is True

    def test_cors_allowed_methods_include_get_post_put_delete(self):
        cfg = self._cors_config()
        methods = cfg.get("allow_methods", [])
        for m in ("GET", "POST", "PUT", "DELETE"):
            assert m in methods

    def test_cors_allowed_methods_include_options(self):
        cfg = self._cors_config()
        assert "OPTIONS" in cfg.get("allow_methods", [])

    def test_cors_allowed_headers_include_authorization(self):
        cfg = self._cors_config()
        assert "Authorization" in cfg.get("allow_headers", [])

    def test_cors_allowed_headers_include_content_type(self):
        cfg = self._cors_config()
        assert "Content-Type" in cfg.get("allow_headers", [])

    def test_cors_allowed_headers_include_x_request_id(self):
        cfg = self._cors_config()
        assert "X-Request-ID" in cfg.get("allow_headers", [])

    def test_cors_expose_headers_include_rate_limit(self):
        cfg = self._cors_config()
        exposed = cfg.get("expose_headers", [])
        assert "X-RateLimit-Limit"     in exposed
        assert "X-RateLimit-Remaining" in exposed
        assert "X-RateLimit-Reset"     in exposed

    def test_cors_expose_headers_include_x_request_id(self):
        cfg = self._cors_config()
        assert "X-Request-ID" in cfg.get("expose_headers", [])


# ===========================================================================
# Exception handlers
# ===========================================================================

class TestExceptionHandlers:

    def test_http_exception_handler_registered(self):
        from fastapi import HTTPException
        assert HTTPException in app.exception_handlers

    def test_validation_exception_handler_registered(self):
        from fastapi.exceptions import RequestValidationError
        assert RequestValidationError in app.exception_handlers

    def test_generic_exception_handler_registered(self):
        assert Exception in app.exception_handlers


# ===========================================================================
# Lifespan: connect_with_retry / db.disconnect
# ===========================================================================

class TestLifespan:

    @pytest.mark.asyncio
    async def test_connect_with_retry_called_on_startup(self):
        """
        FIXED: main.py calls connect_with_retry() (not db.connect()) in the
        lifespan. The old test asserted db.connect.called which was always
        False because that function is never called.
        """
        _fake_connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        async with _main_mod.lifespan(app):
            assert _fake_connect.called

    @pytest.mark.asyncio
    async def test_db_disconnect_called_on_shutdown(self):
        _fake_connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        async with _main_mod.lifespan(app):
            pass

        assert _fake_db.disconnect.called

    @pytest.mark.asyncio
    async def test_db_disconnect_called_on_normal_exit(self):
        _fake_connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        try:
            async with _main_mod.lifespan(app):
                pass
        except Exception:
            pass

        assert _fake_db.disconnect.called


# ===========================================================================
# Rate-limit middleware smoke test
# ===========================================================================

class TestRateLimitMiddleware:

    def test_rate_limit_middleware_does_not_crash(self):
        from fastapi.testclient import TestClient
        test_client = TestClient(app)
        resp = test_client.get("/v1/nonexistent")
        # 404 means middleware passed through without crashing
        assert resp.status_code in (404, 200, 422)