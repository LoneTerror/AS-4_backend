import sys
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.common.route_registry import (
    register_app_routes,
    _auto_title,
    _extract_routes,
    _do_register,
)
import src.common.cache as cache_module

REG = "src.common.route_registry"


@pytest.fixture
def mock_app():
    app = MagicMock(spec=FastAPI)
    app.root_path = "/v1/analytics"
    route1 = MagicMock(spec=APIRoute); route1.path = "/leaderboard"; route1.methods = {"GET"}
    route2 = MagicMock(spec=APIRoute); route2.path = "/redeem";      route2.methods = {"POST"}
    app.routes = [route1, route2]
    return app


def make_mock_db():
    mock_db = MagicMock()
    mock_db.roles.find_many               = AsyncMock()
    mock_db.route_permissions.find_many   = AsyncMock()
    mock_db.route_permissions.create_many = AsyncMock()
    mock_db.route_permissions.update      = AsyncMock()
    return mock_db


def inject_db(mock_db):
    """
    Inject mock_db into sys.modules under every candidate path that
    _do_register's local `from X import db` might resolve to.

    We discover the real path by inspecting what's already in sys.modules
    and looking for a module that actually has a 'db' attribute.
    Works regardless of whether the real path is src.prisma.client,
    src.database, prisma.client, etc.
    """
    candidates = [
        key for key, mod in sys.modules.items()
        if mod is not None and getattr(mod, "db", None) is not None
        and "prisma" in key or "database" in key or "client" in key
    ]

    # Build a fake module wrapper that returns mock_db for `db`
    fake_modules = {}
    for path in candidates:
        fake_mod = MagicMock()
        fake_mod.db = mock_db
        fake_modules[path] = fake_mod

    # Fallback: also patch the most common candidate paths just in case
    for fallback in ("src.prisma.client", "src.database", "prisma.client"):
        if fallback not in fake_modules:
            fake_mod = MagicMock()
            fake_mod.db = mock_db
            fake_modules[fallback] = fake_mod

    return fake_modules


class TestRouteRegistry:

    def test_auto_title(self):
        assert _auto_title("GET:/v1/rewards/catalog")   == "Get Rewards Catalog"
        assert _auto_title("POST:/v1/employees/create") == "Post Employees Create"

    def test_extract_routes(self, mock_app):
        routes = _extract_routes(mock_app)
        assert len(routes) == 2
        assert ("GET", "/v1/analytics/leaderboard") in routes

    # ===========================================================================
    # CORE REGISTRATION LOGIC
    # ===========================================================================

    @pytest.mark.asyncio
    @patch(f"{REG}.asyncio.sleep", AsyncMock())
    async def test_do_register_new_routes(self, mock_app):
        mock_db = make_mock_db()
        mock_db.roles.find_many.return_value = [
            MagicMock(role_code="ADMIN", role_id="r1")
        ]
        mock_db.route_permissions.find_many.return_value = []
        mock_db.route_permissions.create_many.return_value = MagicMock(count=2)

        with patch.dict(sys.modules, inject_db(mock_db)), \
             patch.object(cache_module, "cache_delete", AsyncMock()):

            await _do_register(mock_app, ["ADMIN"], {}, {})

            mock_db.route_permissions.create_many.assert_called_once()

    @pytest.mark.asyncio
    @patch(f"{REG}.asyncio.sleep", AsyncMock())
    async def test_do_register_reactivate_inactive(self, mock_app):
        mock_db = make_mock_db()
        mock_db.roles.find_many.return_value = [
            MagicMock(role_code="ADMIN", role_id="r1")
        ]

        mock_inactive = MagicMock(
            route_key="GET:/v1/analytics/leaderboard",
            role_id="r1",
            is_active=False,
            id="row-999",
        )
        mock_db.route_permissions.find_many.return_value = [mock_inactive]

        with patch.dict(sys.modules, inject_db(mock_db)), \
             patch.object(cache_module, "cache_delete", AsyncMock()):

            await _do_register(mock_app, ["ADMIN"], {}, {})

            mock_db.route_permissions.update.assert_called_once()
            _, kwargs = mock_db.route_permissions.update.call_args
            assert kwargs["data"]["is_active"] is True

    # ===========================================================================
    # PUBLIC API & TIMEOUTS
    # ===========================================================================

    @pytest.mark.asyncio
    @patch(f"{REG}._do_register", AsyncMock())
    async def test_register_app_routes_success(self, mock_app):
        await register_app_routes(mock_app, ["ADMIN"])

    @pytest.mark.asyncio
    @patch(f"{REG}._do_register", AsyncMock(side_effect=asyncio.TimeoutError))
    @patch(f"{REG}.logger")
    async def test_register_app_routes_timeout(self, mock_logger, mock_app):
        await register_app_routes(mock_app, ["ADMIN"])
        mock_logger.warning.assert_called()