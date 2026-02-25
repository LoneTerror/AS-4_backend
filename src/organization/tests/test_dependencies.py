"""
Tests for src/organization/dependencies.py
Covers: get_current_employee, CurrentEmployee
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException


def _make_payload(sub="emp-001", roles=None, email="emp@example.com"):
    return {
        "sub": sub,
        "roles": roles if roles is not None else ["EMPLOYEE"],
        "email": email,
    }


class TestGetCurrentEmployee:

    @pytest.mark.asyncio
    async def test_valid_token_returns_current_employee(self):
        payload = _make_payload(sub="emp-123", roles=["MANAGER"], email="mgr@x.com")

        with patch("src.organization.dependencies.decode_token", return_value=payload):
            from src.organization.dependencies import get_current_employee, CurrentEmployee

            emp = await get_current_employee(token="valid.token")

        assert isinstance(emp, CurrentEmployee)
        assert emp.id == "emp-123"
        assert emp.roles == ["MANAGER"]
        assert emp.email == "mgr@x.com"

    @pytest.mark.asyncio
    async def test_invalid_token_raises_401(self):
        with patch("src.organization.dependencies.decode_token", return_value=None):
            from src.organization.dependencies import get_current_employee

            with pytest.raises(HTTPException) as exc:
                await get_current_employee(token="bad.token")

        assert exc.value.status_code == 401
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}

    @pytest.mark.asyncio
    async def test_exception_during_decode_raises_401(self):
        with patch("src.organization.dependencies.decode_token", side_effect=Exception("JWT error")):
            from src.organization.dependencies import get_current_employee

            with pytest.raises(HTTPException) as exc:
                await get_current_employee(token="bad.token")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_roles_as_string_converted_to_list(self):
        """Some tokens may encode roles as a plain string instead of list."""
        payload = _make_payload(roles="EMPLOYEE")  # string, not list

        with patch("src.organization.dependencies.decode_token", return_value=payload):
            from src.organization.dependencies import get_current_employee

            emp = await get_current_employee(token="token")

        assert isinstance(emp.roles, list)
        assert "EMPLOYEE" in emp.roles

    @pytest.mark.asyncio
    async def test_missing_roles_defaults_to_empty_list(self):
        payload = {"sub": "u1", "email": "u@x.com"}  # no roles key

        with patch("src.organization.dependencies.decode_token", return_value=payload):
            from src.organization.dependencies import get_current_employee

            emp = await get_current_employee(token="token")

        assert emp.roles == []

    @pytest.mark.asyncio
    async def test_missing_email_returns_none(self):
        payload = {"sub": "u1", "roles": ["EMPLOYEE"]}

        with patch("src.organization.dependencies.decode_token", return_value=payload):
            from src.organization.dependencies import get_current_employee

            emp = await get_current_employee(token="token")

        assert emp.email is None


class TestCurrentEmployee:

    def test_current_employee_attributes(self):
        from src.organization.dependencies import CurrentEmployee

        emp = CurrentEmployee(id="u1", roles=["HR_ADMIN"], email="u@x.com")
        assert emp.id == "u1"
        assert emp.roles == ["HR_ADMIN"]
        assert emp.email == "u@x.com"
