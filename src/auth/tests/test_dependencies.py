"""
Tests for src/auth/dependencies.py
Covers: get_current_user, require_roles
"""

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Mock src.core.security BEFORE it is imported anywhere, so the
# RuntimeError("SECRET_KEY environment variable must be set") never fires.
# ---------------------------------------------------------------------------

_security_mock = MagicMock()
_security_mock.decode_token = MagicMock(return_value=None)
sys.modules.setdefault("src.core.security", _security_mock)
sys.modules.setdefault("src.core", MagicMock(security=_security_mock))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(sub="user-123", roles=None):
    return {"sub": sub, "roles": roles if roles is not None else ["EMPLOYEE"]}


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:

    @pytest.mark.asyncio
    async def test_valid_token_returns_current_user(self):
        payload = _make_payload(sub="abc-123", roles=["HR_ADMIN"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import get_current_user, CurrentUser
            user = await get_current_user(token="valid.token.here")

        assert isinstance(user, CurrentUser)
        assert user.id == "abc-123"
        assert user.roles == ["HR_ADMIN"]

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        with patch("src.auth.dependencies.decode_token", return_value=None):
            from src.auth.dependencies import get_current_user

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="bad.token")

        assert exc_info.value.status_code == 401
        assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_roles_defaults_to_empty_list(self):
        payload = {"sub": "user-no-roles"}

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import get_current_user
            user = await get_current_user(token="token")

        assert user.roles == []

    @pytest.mark.asyncio
    async def test_user_id_comes_from_sub_claim(self):
        payload = _make_payload(sub="specific-id-999")

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import get_current_user
            user = await get_current_user(token="token")

        assert user.id == "specific-id-999"


# ---------------------------------------------------------------------------
# require_roles
# ---------------------------------------------------------------------------

class TestRequireRoles:

    @pytest.mark.asyncio
    async def test_allowed_role_grants_access(self):
        payload = _make_payload(roles=["HR_ADMIN"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import require_roles
            checker = require_roles("HR_ADMIN")
            user = await checker(token="token")

        assert user.id == "user-123"
        assert "HR_ADMIN" in user.roles

    @pytest.mark.asyncio
    async def test_disallowed_role_raises_403(self):
        payload = _make_payload(roles=["EMPLOYEE"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import require_roles
            checker = require_roles("HR_ADMIN", "SUPER_ADMIN")

            with pytest.raises(HTTPException) as exc_info:
                await checker(token="token")

        assert exc_info.value.status_code == 403
        assert "permission" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_super_admin_always_bypasses_role_check(self):
        payload = _make_payload(roles=["SUPER_ADMIN"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import require_roles
            checker = require_roles("HR_ADMIN")
            user = await checker(token="token")

        assert user.id == "user-123"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        with patch("src.auth.dependencies.decode_token", return_value=None):
            from src.auth.dependencies import require_roles
            checker = require_roles("HR_ADMIN")

            with pytest.raises(HTTPException) as exc_info:
                await checker(token="bad.token")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_returns_current_user_object_not_dict(self):
        payload = _make_payload(roles=["HR_ADMIN"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import require_roles, CurrentUser
            checker = require_roles("HR_ADMIN")
            user = await checker(token="token")

        assert isinstance(user, CurrentUser)
        assert hasattr(user, "id")
        assert hasattr(user, "roles")

    @pytest.mark.asyncio
    async def test_any_one_matching_role_grants_access(self):
        payload = _make_payload(roles=["MANAGER"])

        with patch("src.auth.dependencies.decode_token", return_value=payload):
            from src.auth.dependencies import require_roles
            checker = require_roles("HR_ADMIN", "MANAGER", "SUPER_ADMIN")
            user = await checker(token="token")

        assert user.id == "user-123"