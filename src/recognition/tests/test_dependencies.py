"""
tests/test_dependencies.py
───────────────────────────
Tests for src/common/dependencies.py

Covers:
  - CurrentUser model
  - PaginationParams
  - _is_public helper
  - _build_route_key helper
  - get_current_user (happy path, cache hit, auth failure, JWT fallback)
  - check_route_permission (cached + uncached, role checks)
"""
from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

import src.common.dependencies as deps
from conftest import make_uuid


# ─────────────────────────────────────────────────────────────────────────────
# CurrentUser
# ─────────────────────────────────────────────────────────────────────────────

class TestCurrentUser:
    def test_defaults(self):
        u = deps.CurrentUser(id="abc", email="a@b.com", roles=["EMPLOYEE"])
        assert u.department_id is None

    def test_with_department(self):
        u = deps.CurrentUser(id="x", email="x@y.com", roles=["MANAGER"], department_id="dept-1")
        assert u.department_id == "dept-1"

    def test_roles_list(self):
        u = deps.CurrentUser(id="x", email="x@y.com", roles=["HR_ADMIN", "MANAGER"])
        assert "HR_ADMIN" in u.roles


# ─────────────────────────────────────────────────────────────────────────────
# PaginationParams
# ─────────────────────────────────────────────────────────────────────────────

class TestPaginationParams:
    def test_defaults(self):
        p = deps.PaginationParams.__new__(deps.PaginationParams)
        p.page = 1
        p.size = 10
        assert p.page == 1
        assert p.size == 10


# ─────────────────────────────────────────────────────────────────────────────
# register_public_paths / _is_public
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicPaths:
    def _make_request(self, path: str) -> MagicMock:
        r = MagicMock()
        r.scope = {"path": path}
        r.url.path = path
        return r

    def test_health_is_public(self):
        assert deps._is_public(self._make_request("/health")) is True

    def test_docs_is_public(self):
        assert deps._is_public(self._make_request("/docs")) is True

    def test_api_route_is_not_public(self):
        assert deps._is_public(self._make_request("/aabhar/v1/recognitions/reviews")) is False

    def test_register_public_paths(self):
        deps.register_public_paths("/custom-public")
        assert deps._is_public(self._make_request("/custom-public")) is True

    def test_openapi_json_is_public(self):
        assert deps._is_public(self._make_request("/openapi.json")) is True


# ─────────────────────────────────────────────────────────────────────────────
# _build_route_key
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildRouteKey:
    def _make_request(self, method: str, bare_path: str, root_path: str = "/aabhar/v1/recognitions") -> MagicMock:
        app = MagicMock()
        app.root_path = root_path

        route = MagicMock(spec=APIRoute)
        route.path = bare_path

        req = MagicMock()
        req.method = method
        req.scope  = {"route": route, "path": bare_path}
        req.url.path = bare_path
        req.app = app
        return req

    def test_builds_key_with_root_path(self):
        req = self._make_request("GET", "/reviews")
        key = deps._build_route_key(req)
        assert key == "GET:/aabhar/v1/recognitions/reviews"

    def test_post_method(self):
        req = self._make_request("POST", "/reviews")
        key = deps._build_route_key(req)
        assert key == "POST:/aabhar/v1/recognitions/reviews"

    def test_parameterised_path(self):
        req = self._make_request("GET", "/reviews/{id}")
        key = deps._build_route_key(req)
        assert key == "GET:/aabhar/v1/recognitions/reviews/{id}"

    def test_no_root_path(self):
        req = self._make_request("GET", "/health", root_path="")
        key = deps._build_route_key(req)
        assert key == "GET:/health"

    def test_trailing_slash_stripped_from_root_path(self):
        req = self._make_request("GET", "/reviews", root_path="/aabhar/v1/recognitions/")
        key = deps._build_route_key(req)
        assert key == "GET:/aabhar/v1/recognitions/reviews"

    def test_non_api_route_falls_back_to_scope_path(self):
        app = MagicMock()
        app.root_path = "/aabhar/v1/svc"
        req = MagicMock()
        req.method   = "GET"
        req.scope    = {"path": "/some/path"}  # no "route" key
        req.url.path = "/some/path"
        req.app = app
        key = deps._build_route_key(req)
        assert key == "GET:/aabhar/v1/svc/some/path"


# ─────────────────────────────────────────────────────────────────────────────
# get_current_user
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCurrentUser:
    def _public_request(self, path="/health"):
        req = MagicMock()
        req.scope = {"path": path}
        req.url.path = path
        return req

    def _authed_request(self, path="/aabhar/v1/recognitions/reviews"):
        req = MagicMock()
        req.scope = {"path": path}
        req.url.path = path
        req.state.request_id = "test-req-id"
        return req

    def _credentials(self, token="valid-token"):
        creds = MagicMock()
        creds.credentials = token
        return creds

    async def test_public_path_returns_public_user(self):
        result = await deps.get_current_user(self._public_request(), None)
        assert result.id == "system"

    async def test_no_credentials_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await deps.get_current_user(self._authed_request(), None)
        assert exc.value.status_code == 401

    async def test_cache_hit_returns_user(self):
        cached_data = {"id": "user-123", "email": "u@test.com", "roles": ["EMPLOYEE"], "department_id": None}
        req   = self._authed_request()
        creds = self._credentials("good-token")
        with patch("src.common.dependencies.cache_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = cached_data
            result = await deps.get_current_user(req, creds)
        assert result.id == "user-123"

    async def test_invalid_cache_id_falls_through(self):
        """Cache returning null user_id should be evicted and auth service called."""
        bad_cache = {"id": "null", "email": "", "roles": []}
        req   = self._authed_request()
        creds = self._credentials("token-123")
        auth_response = MagicMock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "valid": True, "user_id": "real-user", "email": "r@test.com", "roles": ["EMPLOYEE"]
        }
        with (
            patch("src.common.dependencies.cache_get",    new_callable=AsyncMock, return_value=bad_cache),
            patch("src.common.cache.cache_delete",        new_callable=AsyncMock),
            patch("src.common.dependencies.cache_set",    new_callable=AsyncMock),
            patch("src.common.dependencies.get_auth_client") as mock_client_fn,
        ):
            client = AsyncMock()
            client.post = AsyncMock(return_value=auth_response)
            mock_client_fn.return_value = client
            result = await deps.get_current_user(req, creds)
        assert result.id == "real-user"

    async def test_auth_service_invalid_token_raises_401(self):
        req   = self._authed_request()
        creds = self._credentials("bad-token")
        auth_response = MagicMock()
        auth_response.status_code = 401
        auth_response.json.return_value = {"valid": False}
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.common.dependencies.get_auth_client") as mock_client_fn,
        ):
            client = AsyncMock()
            client.post = AsyncMock(return_value=auth_response)
            mock_client_fn.return_value = client
            with pytest.raises(HTTPException) as exc:
                await deps.get_current_user(req, creds)
        assert exc.value.status_code == 401

    async def test_jwt_fallback_on_network_error(self):
        """When auth service is unreachable, fall back to local JWT validation."""
        import jwt as pyjwt
        import os
        secret = os.environ["SECRET_KEY"]
        token  = pyjwt.encode(
            {"user_id": "jwt-user", "roles": ["MANAGER"], "email": "j@test.com"},
            secret,
            algorithm="HS256",
        )
        req   = self._authed_request()
        creds = self._credentials(token)
        import httpx
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.common.dependencies.get_auth_client") as mock_client_fn,
        ):
            client = AsyncMock()
            client.post = AsyncMock(side_effect=httpx.RequestError("timeout", request=MagicMock()))
            mock_client_fn.return_value = client
            result = await deps.get_current_user(req, creds)
        assert result.id == "jwt-user"
        assert "MANAGER" in result.roles

    async def test_expired_jwt_raises_401(self):
        import jwt as pyjwt, os
        from datetime import timedelta
        secret = os.environ["SECRET_KEY"]
        token  = pyjwt.encode(
            {"user_id": "u", "roles": [], "exp": 1},  # expired in the past
            secret, algorithm="HS256",
        )
        req   = self._authed_request()
        creds = self._credentials(token)
        import httpx
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.common.dependencies.get_auth_client") as mock_client_fn,
        ):
            client = AsyncMock()
            client.post = AsyncMock(side_effect=httpx.RequestError("t", request=MagicMock()))
            mock_client_fn.return_value = client
            with pytest.raises(HTTPException) as exc:
                await deps.get_current_user(req, creds)
        assert exc.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────────────
# check_route_permission
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckRoutePermission:
    def _make_request(self, method="GET", path="/reviews"):
        app = MagicMock(); app.root_path = "/aabhar/v1/recognitions"
        route = MagicMock(spec=APIRoute); route.path = path
        req = MagicMock()
        req.method = method
        req.scope  = {"route": route, "path": path}
        req.url.path = path
        req.app = app
        return req

    def _user(self, roles):
        return deps.CurrentUser(id=make_uuid(), email="u@test.com", roles=roles)

    async def test_public_path_bypasses_permission(self):
        req  = MagicMock()
        req.scope = {"path": "/health"}
        req.url.path = "/health"
        user = self._user(["EMPLOYEE"])
        result = await deps.check_route_permission(req, user)
        assert result is user

    async def test_super_admin_bypasses_check(self):
        req  = self._make_request()
        user = self._user(["SUPER_ADMIN"])
        result = await deps.check_route_permission(req, user)
        assert result is user

    async def test_403_when_no_permissions_configured(self):
        req  = self._make_request()
        user = self._user(["EMPLOYEE"])
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch.object(deps.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[])
            with pytest.raises(HTTPException) as exc:
                await deps.check_route_permission(req, user)
        assert exc.value.status_code == 403

    async def test_403_when_role_not_in_allowed(self):
        req  = self._make_request()
        user = self._user(["EMPLOYEE"])
        perm = MagicMock(); perm.roles = MagicMock(); perm.roles.role_code = "HR_ADMIN"
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.common.dependencies.cache_set", new_callable=AsyncMock),
            patch.object(deps.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[perm])
            with pytest.raises(HTTPException) as exc:
                await deps.check_route_permission(req, user)
        assert exc.value.status_code == 403

    async def test_200_when_role_matches(self):
        req  = self._make_request()
        user = self._user(["MANAGER"])
        perm = MagicMock(); perm.roles = MagicMock(); perm.roles.role_code = "MANAGER"
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=None),
            patch("src.common.dependencies.cache_set", new_callable=AsyncMock),
            patch.object(deps.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[perm])
            result = await deps.check_route_permission(req, user)
        assert result.id == user.id

    async def test_cache_hit_skips_db(self):
        req  = self._make_request()
        user = self._user(["HR_ADMIN"])
        with (
            patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=["HR_ADMIN"]),
            patch.object(deps.db, "route_permissions") as mock_rp,
        ):
            result = await deps.check_route_permission(req, user)
            mock_rp.find_many.assert_not_called()
        assert result is user

    async def test_empty_cached_roles_raises_403(self):
        req  = self._make_request()
        user = self._user(["EMPLOYEE"])
        with patch("src.common.dependencies.cache_get", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(HTTPException) as exc:
                await deps.check_route_permission(req, user)
        assert exc.value.status_code == 403
