"""
test_dependencies.py
Unit tests for src/recognition/dependencies.py

Covers:
- get_current_user(): token validation, role normalisation, error paths
- require_roles(): factory, SUPER_ADMIN bypass, role enforcement
"""

import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from fastapi import HTTPException, Request

sys.path.insert(0, os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Patch httpx before importing the real dependencies module
# ---------------------------------------------------------------------------
import types, importlib

# Ensure the stub namespace exists (conftest.py already did this but we're
# explicit here so the file is runnable standalone via pytest).
for _p in ["src", "src.prisma", "src.prisma.client", "src.recognition",
           "src.recognition.dependencies", "src.recognition.schemas",
           "src.common", "src.common.middleware"]:
    if _p not in sys.modules:
        sys.modules[_p] = types.ModuleType(_p)

# Import the REAL dependencies module from uploads dir
import importlib.util, pathlib

_deps_path = pathlib.Path(__file__).parent.parent / "dependencies.py"
_spec = importlib.util.spec_from_file_location("dep_module", _deps_path)
_dep_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dep_module)

get_current_user = _dep_module.get_current_user
require_roles    = _dep_module.require_roles
CurrentUser      = _dep_module.CurrentUser

AUTH_URL = "https://auth.internal/validate"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_request(request_id: str | None = "req-abc"):
    req = MagicMock(spec=Request)
    req.headers = {"X-Request-ID": request_id} if request_id else {}
    return req


def make_credentials(token: str = "valid-token"):
    creds = MagicMock()
    creds.credentials = token
    return creds


def make_auth_response(valid=True, user_id="u-1", email="u@test.com",
                       roles=None, department_id=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "valid": valid,
        "user_id": user_id,
        "email": email,
        "roles": roles or ["employee"],
        "department_id": department_id,
    }
    return resp


# ===========================================================================
# get_current_user
# ===========================================================================

class TestGetCurrentUser:

    @pytest.mark.asyncio
    async def test_valid_token_returns_current_user(self):
        req   = make_request()
        creds = make_credentials("good-token")

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(
                valid=True, user_id="u-1", email="u@test.com", roles=["employee", "manager"]
            ))
            mock_client_cls.return_value = mock_client

            user = await get_current_user(req, creds)

        assert isinstance(user, CurrentUser)
        assert user.id    == "u-1"
        assert user.email == "u@test.com"

    @pytest.mark.asyncio
    async def test_roles_are_uppercased(self):
        req   = make_request()
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(
                roles=["employee", "hr_admin"]
            ))
            mock_client_cls.return_value = mock_client

            user = await get_current_user(req, creds)

        assert "EMPLOYEE" in user.roles
        assert "HR_ADMIN" in user.roles
        assert "employee" not in user.roles

    @pytest.mark.asyncio
    async def test_auth_service_non_200_raises_401(self):
        req   = make_request()
        creds = make_credentials("bad-token")

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(status_code=401))
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_current_user(req, creds)

        assert exc.value.status_code == 401
        assert "Invalid or expired" in exc.value.detail

    @pytest.mark.asyncio
    async def test_valid_false_in_response_raises_401(self):
        req   = make_request()
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(
                status_code=200, valid=False
            ))
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_current_user(req, creds)

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_request_error_raises_503(self):
        import httpx
        req   = make_request()
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(side_effect=httpx.RequestError("timeout"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_current_user(req, creds)

        assert exc.value.status_code == 503
        assert "unavailable" in exc.value.detail

    @pytest.mark.asyncio
    async def test_department_id_is_optional(self):
        req   = make_request()
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(department_id=None))
            mock_client_cls.return_value = mock_client

            user = await get_current_user(req, creds)

        assert user.department_id is None

    @pytest.mark.asyncio
    async def test_department_id_populated_when_present(self):
        req   = make_request()
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            mock_client.post       = AsyncMock(return_value=make_auth_response(department_id="dept-99"))
            mock_client_cls.return_value = mock_client

            user = await get_current_user(req, creds)

        assert user.department_id == "dept-99"

    @pytest.mark.asyncio
    async def test_request_id_forwarded_to_auth_service(self):
        req   = make_request(request_id="trace-xyz")
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            post_mock = AsyncMock(return_value=make_auth_response())
            mock_client.post = post_mock
            mock_client_cls.return_value = mock_client

            await get_current_user(req, creds)

        call_kwargs = post_mock.call_args[1]
        assert call_kwargs.get("headers", {}).get("X-Request-ID") == "trace-xyz"

    @pytest.mark.asyncio
    async def test_no_request_id_sends_no_header(self):
        req   = make_request(request_id=None)
        creds = make_credentials()

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            post_mock = AsyncMock(return_value=make_auth_response())
            mock_client.post = post_mock
            mock_client_cls.return_value = mock_client

            await get_current_user(req, creds)

        # headers kwarg should be None or not contain X-Request-ID
        call_kwargs = post_mock.call_args[1]
        headers = call_kwargs.get("headers")
        assert headers is None or "X-Request-ID" not in (headers or {})

    @pytest.mark.asyncio
    async def test_token_sent_in_request_body(self):
        req   = make_request()
        creds = make_credentials("my-secret-token")

        with patch.object(_dep_module, "AUTH_SERVICE_URL", AUTH_URL), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__  = AsyncMock(return_value=None)
            post_mock = AsyncMock(return_value=make_auth_response())
            mock_client.post = post_mock
            mock_client_cls.return_value = mock_client

            await get_current_user(req, creds)

        call_kwargs = post_mock.call_args[1]
        assert call_kwargs["json"] == {"token": "my-secret-token"}


# ===========================================================================
# require_roles
# ===========================================================================

class TestRequireRoles:
    """
    require_roles() is a factory that returns an inner async function
    `role_checker(current_user)`. We call it directly by passing the
    already-resolved user as a keyword argument, bypassing FastAPI DI.
    """

    def _make_user(self, user_id="u-1", roles=None):
        return _dep_module.CurrentUser(id=user_id, email="u@test.com",
                                       roles=roles or ["EMPLOYEE"])

    @pytest.mark.asyncio
    async def test_user_with_allowed_role_passes(self):
        role_checker = _dep_module.require_roles("EMPLOYEE", "MANAGER")
        user = self._make_user(roles=["EMPLOYEE"])

        result = await role_checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_user_without_required_role_gets_403(self):
        role_checker = _dep_module.require_roles("MANAGER", "HR_ADMIN")
        user = self._make_user(roles=["EMPLOYEE"])

        with pytest.raises(HTTPException) as exc:
            await role_checker(current_user=user)

        assert exc.value.status_code == 403
        assert "Insufficient permissions" in exc.value.detail

    @pytest.mark.asyncio
    async def test_super_admin_bypasses_role_check(self):
        role_checker = _dep_module.require_roles("MANAGER")
        user = self._make_user(roles=["SUPER_ADMIN"])

        # SUPER_ADMIN must pass even though MANAGER is required
        result = await role_checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_role_comparison_is_case_insensitive(self):
        """require_roles("employee") should match a user with roles=["EMPLOYEE"]"""
        role_checker = _dep_module.require_roles("employee")
        user = self._make_user(roles=["EMPLOYEE"])

        result = await role_checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_multiple_roles_any_match_passes(self):
        role_checker = _dep_module.require_roles("MANAGER", "HR_ADMIN")
        user = self._make_user(roles=["HR_ADMIN"])

        result = await role_checker(current_user=user)
        assert result == user

    @pytest.mark.asyncio
    async def test_empty_user_roles_gets_403(self):
        """User with zero roles must be denied even when EMPLOYEE is required."""
        from types import SimpleNamespace

        role_checker = _dep_module.require_roles("EMPLOYEE")
        user = SimpleNamespace(roles=[])

        # Verify the logic directly — no DI, no FastAPI, pure coroutine call
        raised = False
        try:
            await role_checker(current_user=user)
        except HTTPException as e:
            raised = True
            assert e.status_code == 403
            assert "Insufficient permissions" in e.detail

        assert raised, (
            "Expected HTTPException 403 but require_roles did not raise. "
            f"role_checker={role_checker}, user.roles={user.roles}"
        )