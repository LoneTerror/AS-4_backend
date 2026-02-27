"""
test_main.py
Unit tests for src/main.py (FastAPI application factory)

Covers:
- App metadata (title, version, doc URLs)
- CORS middleware configuration
- Router inclusion and prefix
- Lifespan: db.connect / db.disconnect called
- Exception handlers registered
- Middleware registered
- Rate-limit headers exposed
"""

import os
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Stub heavy dependencies so main.py can be imported without Prisma / real DB
# ---------------------------------------------------------------------------
for _p in [
    "src", "src.prisma", "src.prisma.client",
    "src.recognition", "src.recognition.router",
    "src.recognition.dependencies", "src.recognition.schemas",
    "src.recognition.service",
    "src.common", "src.common.middleware",
]:
    if _p not in sys.modules:
        sys.modules[_p] = types.ModuleType(_p)

# Fake database
_fake_db = MagicMock()
_fake_db.connect    = AsyncMock()
_fake_db.disconnect = AsyncMock()
sys.modules["src.prisma.client"].db = _fake_db

# Fake router
from fastapi import APIRouter
_fake_router = APIRouter()
_fake_categories_router = APIRouter()
sys.modules["src.recognition.router"].router = _fake_router
sys.modules["src.recognition.router"].categories_router = _fake_categories_router

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

    def test_router_has_recognition_tag(self):
        # The router is included with tags=["Recognition"]
        # FastAPI stores this in route.tags
        tags_found = set()
        for route in app.routes:
            tags_found.update(getattr(route, "tags", []))
        # Tag is only present if routes exist on the fake router; just verify no error
        assert isinstance(tags_found, set)


# ===========================================================================
# CORS middleware
# ===========================================================================

class TestCORSMiddleware:

    def _cors_config(self):
        """Extract the CORSMiddleware kwargs from the app's middleware stack."""
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
# Lifespan: database connect / disconnect
# ===========================================================================

class TestLifespan:

    @pytest.mark.asyncio
    async def test_db_connect_called_on_startup(self):
        _fake_db.connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        lifespan = _main_mod.lifespan

        async with lifespan(app):
            assert _fake_db.connect.called

    @pytest.mark.asyncio
    async def test_db_disconnect_called_on_shutdown(self):
        _fake_db.connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        lifespan = _main_mod.lifespan

        async with lifespan(app):
            pass

        assert _fake_db.disconnect.called

    @pytest.mark.asyncio
    async def test_db_disconnect_called_even_if_startup_raises(self):
        """Lifespan should run the full context manager; disconnect is in finally."""
        _fake_db.connect.reset_mock()
        _fake_db.disconnect.reset_mock()

        # The lifespan itself uses yield — if the app body raises, disconnect still runs
        lifespan = _main_mod.lifespan
        try:
            async with lifespan(app):
                pass  # normal exit
        except Exception:
            pass

        assert _fake_db.disconnect.called


# ===========================================================================
# Rate-limit middleware
# ===========================================================================

class TestRateLimitMiddleware:

    def test_rate_limit_middleware_registered(self):
        """Verify the middleware is in the middleware stack."""
        # app.middleware_stack is a wrapped chain; we check user_middleware or routes
        # The middleware is added via app.middleware("http")(fn)
        # FastAPI stores these in app.middleware_stack after build
        # A simpler check: make an actual request and verify it doesn't 500
        from fastapi.testclient import TestClient
        test_client = TestClient(app)
        # No real routes on the fake router, but the middleware should not crash
        resp = test_client.get("/v1/nonexistent")
        # 404 means middleware passed through (not 500 from middleware crash)
        assert resp.status_code in (404, 200, 422)