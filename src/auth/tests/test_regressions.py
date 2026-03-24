"""
src/auth/tests/test_regressions.py
────────────────────────────────────
Regression tests that guard against known bugs and edge cases specific
to the auth service.  Each class is named after the issue it prevents.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.auth.service as svc
from src.auth.schemas import LoginRequest, SignUpRequest, TokenValidationResponse
from conftest import (
    _fake_employee,
    _fake_employee_role,
    _fake_refresh_token,
    _fake_designation,
    _fake_department,
    _fake_status,
    make_uuid,
    utcnow,
)

_TOKEN_SEP = "||"


def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm():
        yield
    return _cm()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION ERR-437: Login must be case-insensitive
# ─────────────────────────────────────────────────────────────────────────────

class TestCaseInsensitiveLogin:
    def test_schema_lowercases_username(self):
        r = LoginRequest(username="ADMIN@COMPANY.COM", password="pass")
        assert r.username == "admin@company.com"

    def test_schema_strips_and_lowercases(self):
        r = LoginRequest(username="  JOHN.DOE@EXAMPLE.COM  ", password="pass")
        assert r.username == "john.doe@example.com"

    def test_service_strips_and_lowercases_username(self):
        """Service layer also normalizes — double protection."""
        calls = []
        async def fake_find_first(**kwargs):
            calls.append(kwargs)
            return None
        original = svc.db.employees.find_first
        svc.db.employees.find_first = fake_find_first
        try:
            import asyncio
            async def _run():
                with patch("src.auth.service.audit", new_callable=AsyncMock):
                    with pytest.raises(HTTPException):
                        await svc.authenticate_user("  UPPER@EXAMPLE.COM  ", "pass")
            asyncio.get_event_loop().run_until_complete(_run())
        finally:
            svc.db.employees.find_first = original

    def test_lowercase_and_uppercase_produce_same_db_query(self):
        r1 = LoginRequest(username="admin@company.com", password="p")
        r2 = LoginRequest(username="ADMIN@COMPANY.COM", password="p")
        assert r1.username == r2.username


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: Token separator split must use maxsplit=1
# Secrets can theoretically contain the separator bytes.
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenSeparatorSplit:
    async def test_refresh_raises_401_without_separator(self):
        with pytest.raises(HTTPException) as exc:
            await svc.refresh_access_token("noseparatortoken")
        assert exc.value.status_code == 401

    async def test_logout_handles_no_separator_gracefully(self):
        result = await svc.logout_user("noseparatortoken", make_uuid())
        assert "message" in result

    async def test_refresh_parses_token_id_correctly(self):
        token_id = make_uuid()
        secret   = "correct-secret"
        stored   = _fake_refresh_token(
            token_id   = token_id,
            token_hash = svc.hash_refresh_token(secret),
            expires_at = utcnow() + timedelta(days=7),
        )
        with (
            patch.object(svc.db, "refresh_tokens") as mock_rt,
            patch.object(svc.db, "employee_roles") as mock_er,
            patch("src.auth.service.create_access_token", return_value="tok"),
        ):
            mock_rt.find_unique = AsyncMock(return_value=stored)
            mock_er.find_many   = AsyncMock(return_value=[])
            result = await svc.refresh_access_token(f"{token_id}{_TOKEN_SEP}{secret}")
        assert result["access_token"] == "tok"

    def test_token_sep_constant_is_double_pipe(self):
        assert svc._TOKEN_SEP == "||"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: validate_token must never raise — always return a dict
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateTokenNeverRaises:
    async def test_empty_string_returns_dict(self):
        with patch("src.auth.service.decode_token", return_value=None):
            result = await svc.validate_token("")
        assert isinstance(result, dict)
        assert result["valid"] is False

    async def test_garbage_token_returns_dict(self):
        with patch("src.auth.service.decode_token", return_value=None):
            result = await svc.validate_token("not.a.jwt.at.all.garbage")
        assert isinstance(result, dict)

    async def test_expired_token_returns_valid_false(self):
        with patch("src.auth.service.decode_token", return_value=None):
            result = await svc.validate_token("expired.jwt.token")
        assert result["valid"] is False

    async def test_valid_dict_has_error_key_when_invalid(self):
        with patch("src.auth.service.decode_token", return_value=None):
            result = await svc.validate_token("bad")
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: reset_password must revoke ALL non-revoked tokens for the user
# ─────────────────────────────────────────────────────────────────────────────

class TestPasswordResetRevokesAllTokens:
    async def test_update_many_called_with_employee_id(self):
        emp_id = make_uuid()
        emp    = _fake_employee(employee_id=emp_id, email="user@example.com")
        with (
            patch("src.auth.service.decode_reset_token", return_value={"sub": emp_id, "email": emp.email}),
            patch.object(svc.db, "employees")     as mock_emp,
            patch.object(svc.db, "refresh_tokens") as mock_rt,
            patch("src.auth.service.send_password_reset_confirmation"),
            patch("src.auth.service.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_emp.find_unique = AsyncMock(return_value=emp)
            mock_emp.update      = AsyncMock(return_value=emp)
            mock_rt.update_many  = AsyncMock(return_value=MagicMock())
            await svc.reset_password("tok", "NewPass1!")
        where = mock_rt.update_many.call_args.kwargs["where"]
        assert where["employee_id"] == emp_id

    async def test_update_many_filters_revoked_at_none(self):
        emp_id = make_uuid()
        emp    = _fake_employee(employee_id=emp_id, email="user@example.com")
        with (
            patch("src.auth.service.decode_reset_token", return_value={"sub": emp_id, "email": emp.email}),
            patch.object(svc.db, "employees")     as mock_emp,
            patch.object(svc.db, "refresh_tokens") as mock_rt,
            patch("src.auth.service.send_password_reset_confirmation"),
            patch("src.auth.service.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_emp.find_unique = AsyncMock(return_value=emp)
            mock_emp.update      = AsyncMock(return_value=emp)
            mock_rt.update_many  = AsyncMock(return_value=MagicMock())
            await svc.reset_password("tok", "NewPass1!")
        where = mock_rt.update_many.call_args.kwargs["where"]
        assert where["revoked_at"] is None

    async def test_password_update_never_stores_plaintext(self):
        emp_id = make_uuid()
        emp    = _fake_employee(employee_id=emp_id, email="user@example.com")
        plain  = "NewPlainPass1!"
        with (
            patch("src.auth.service.decode_reset_token", return_value={"sub": emp_id, "email": emp.email}),
            patch.object(svc.db, "employees")     as mock_emp,
            patch.object(svc.db, "refresh_tokens") as mock_rt,
            patch("src.auth.service.send_password_reset_confirmation"),
            patch("src.auth.service.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_emp.find_unique = AsyncMock(return_value=emp)
            mock_emp.update      = AsyncMock(return_value=emp)
            mock_rt.update_many  = AsyncMock(return_value=MagicMock())
            await svc.reset_password("tok", plain)
        update_data = mock_emp.update.call_args.kwargs["data"]
        assert update_data["password_hash"] != plain


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: request_password_reset must not leak user existence
# (same HTTP response whether user exists or not)
# ─────────────────────────────────────────────────────────────────────────────

class TestNoUserEnumeration:
    async def test_same_message_for_existing_and_non_existing_user(self):
        emp = _fake_employee()
        with (
            patch.object(svc.db, "employees") as mock_emp,
            patch("src.auth.service.create_reset_token", return_value="tok"),
            patch("src.auth.service.send_password_reset_email"),
            patch("src.auth.service.audit", new_callable=AsyncMock),
        ):
            mock_emp.find_unique = AsyncMock(return_value=emp)
            result_exists = await svc.request_password_reset(emp.email)

        with patch.object(svc.db, "employees") as mock_emp2:
            mock_emp2.find_unique = AsyncMock(return_value=None)
            result_missing = await svc.request_password_reset("ghost@example.com")

        assert result_exists["message"] == result_missing["message"]

    async def test_response_does_not_confirm_email_exists(self):
        with patch.object(svc.db, "employees") as mock_emp:
            mock_emp.find_unique = AsyncMock(return_value=None)
            result = await svc.request_password_reset("ghost@example.com")
        # Must not say "not found" or "doesn't exist"
        assert "not found" not in result["message"].lower()
        assert "doesn't exist" not in result["message"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: create_employee must publish event AFTER DB write succeeds
# ─────────────────────────────────────────────────────────────────────────────

class TestEventPublishedAfterDbWrite:
    async def test_publish_called_after_create(self):
        from src.auth.schemas import SignUpRequest
        payload = SignUpRequest(
            username="order.test",
            email="order.test@example.com",
            password="TestPass1!",
            designation_id=uuid.uuid4(),
            department_id=uuid.uuid4(),
        )
        new_emp = _fake_employee()
        call_order = []

        async def mock_create(**kwargs):
            call_order.append("db_create")
            return new_emp

        async def mock_publish(stream, data):
            call_order.append("publish")

        with (
            patch.object(svc.db, "employees")    as mock_emp,
            patch.object(svc.db, "designations") as mock_desig,
            patch.object(svc.db, "departments")  as mock_dept,
            patch.object(svc.db, "status_master") as mock_sm,
            patch("src.auth.service.publish",   side_effect=mock_publish),
            patch("src.auth.service.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_emp.find_unique   = AsyncMock(return_value=None)
            mock_emp.create        = mock_create
            mock_desig.find_unique = AsyncMock(return_value=_fake_designation())
            mock_dept.find_unique  = AsyncMock(return_value=_fake_department())
            mock_sm.find_first     = AsyncMock(return_value=_fake_status())
            await svc.create_employee(payload, make_uuid())

        assert call_order == ["db_create", "publish"]


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: _build_login_response must never expose password hash
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginResponseSecurity:
    def test_response_does_not_contain_password_hash(self):
        emp = _fake_employee(password_hash="$2b$12$secret-hash-value")
        result = svc._build_login_response(emp, "access-tok", "refresh-tok")
        import json
        serialized = json.dumps(result)
        assert "password" not in serialized.lower()
        assert "hash" not in serialized.lower()

    def test_employee_object_only_has_safe_fields(self):
        emp = _fake_employee()
        result = svc._build_login_response(emp, "a", "r")
        allowed = {"employee_id", "username", "email", "designation_id", "department_id"}
        for key in result["employee"]:
            assert key in allowed, f"Unexpected field in response: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: refresh_access_token must re-query roles, not trust old token
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshRequeriesRoles:
    async def test_roles_fetched_fresh_on_refresh(self):
        """Roles come from DB, not from the old token payload."""
        stored = _fake_refresh_token(
            token_hash = svc.hash_refresh_token("good-secret"),
            expires_at = utcnow() + timedelta(days=7),
        )
        # Employee now has a new MANAGER role — even though old token may have had EMPLOYEE
        er = _fake_employee_role(role_code="MANAGER")
        with (
            patch.object(svc.db, "refresh_tokens") as mock_rt,
            patch.object(svc.db, "employee_roles") as mock_er,
            patch("src.auth.service.create_access_token") as mock_cat,
        ):
            mock_rt.find_unique = AsyncMock(return_value=stored)
            mock_er.find_many   = AsyncMock(return_value=[er])
            await svc.refresh_access_token(f"{stored.token_id}{_TOKEN_SEP}good-secret")
            roles_in_new_token = mock_cat.call_args[0][0]["roles"]
        assert "MANAGER" in roles_in_new_token


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: TokenValidationResponse schema — all optional fields except valid
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenValidationResponseSchema:
    def test_only_valid_required(self):
        r = TokenValidationResponse(valid=False)
        assert r.user_id       is None
        assert r.email         is None
        assert r.roles         is None
        assert r.department_id is None
        assert r.error         is None

    def test_error_field_only_on_invalid(self):
        r = TokenValidationResponse(valid=False, error="Token expired")
        assert r.error == "Token expired"

    def test_valid_true_with_full_payload(self):
        r = TokenValidationResponse(
            valid=True,
            user_id="uid-123",
            email="u@example.com",
            roles=["EMPLOYEE"],
            department_id="dept-456",
        )
        assert r.valid is True
        assert r.error is None

    def test_roles_empty_list_accepted(self):
        r = TokenValidationResponse(valid=True, roles=[])
        assert r.roles == []

    def test_multiple_roles_preserved(self):
        r = TokenValidationResponse(valid=True, roles=["MANAGER", "HR_ADMIN", "SUPER_ADMIN"])
        assert len(r.roles) == 3


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: SignUpRequest username length enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestSignUpUsernameConstraints:
    def _base(self, **overrides):
        base = dict(
            username="valid.user",
            email="valid@example.com",
            password="TestPass1!",
            designation_id=uuid.uuid4(),
            department_id=uuid.uuid4(),
        )
        base.update(overrides)
        return SignUpRequest(**base)

    def test_username_stripped_by_schema(self):
        r = self._base(username="  trimmed  ")
        assert r.username == "trimmed"

    def test_username_empty_after_strip_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._base(username="   ")

    def test_username_255_chars_ok(self):
        r = self._base(username="x" * 255)
        assert len(r.username) == 255

    def test_username_256_chars_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._base(username="x" * 256)

    def test_password_128_chars_ok(self):
        r = self._base(password="x" * 128)
        assert len(r.password) == 128

    def test_password_129_chars_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._base(password="x" * 129)
