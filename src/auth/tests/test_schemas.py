"""
src/auth/tests/test_schemas.py
───────────────────────────────
Pydantic schema validation tests against the real src/auth/schemas.py.
No DB or IO involved — pure model-layer tests.
"""
from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from src.auth.schemas import (
    EmployeeResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SignUpRequest,
    TokenResponse,
    TokenValidationRequest,
    TokenValidationResponse,
)

DESIG_ID = uuid.uuid4()
DEPT_ID  = uuid.uuid4()
MGR_ID   = uuid.uuid4()
EMP_ID   = uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# SignUpRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestSignUpRequest:
    def _valid(self, **overrides):
        base = dict(
            username="john.doe",
            email="john.doe@example.com",
            password="SecurePass1",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
        )
        base.update(overrides)
        return SignUpRequest(**base)

    # ── username ──────────────────────────────────────────────────────────────
    def test_valid_minimal(self):
        r = self._valid()
        assert r.username == "john.doe"

    def test_username_whitespace_stripped(self):
        r = self._valid(username="  john.doe  ")
        assert r.username == "john.doe"

    def test_username_empty_raises(self):
        with pytest.raises(ValidationError):
            self._valid(username="")

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(username="x" * 256)

    def test_username_max_length_ok(self):
        r = self._valid(username="x" * 255)
        assert len(r.username) == 255

    def test_username_single_char_ok(self):
        r = self._valid(username="a")
        assert r.username == "a"

    # ── email ──────────────────────────────────────────────────────────────────
    def test_valid_email(self):
        r = self._valid(email="test@domain.org")
        assert r.email == "test@domain.org"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            self._valid(email="not-an-email")

    def test_email_missing_domain_raises(self):
        with pytest.raises(ValidationError):
            self._valid(email="user@")

    def test_email_missing_at_raises(self):
        with pytest.raises(ValidationError):
            self._valid(email="userdomain.com")

    # ── password ───────────────────────────────────────────────────────────────
    def test_password_stripped(self):
        r = self._valid(password="  SecurePass1  ")
        assert r.password == "SecurePass1"

    def test_password_empty_raises(self):
        with pytest.raises(ValidationError):
            self._valid(password="")

    def test_password_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(password="x" * 129)

    def test_password_max_length_ok(self):
        r = self._valid(password="x" * 128)
        assert len(r.password) == 128

    def test_password_length_one_ok(self):
        r = self._valid(password="p")
        assert r.password == "p"

    # ── UUIDs ──────────────────────────────────────────────────────────────────
    def test_designation_id_is_uuid(self):
        r = self._valid()
        assert r.designation_id == DESIG_ID

    def test_department_id_is_uuid(self):
        r = self._valid()
        assert r.department_id == DEPT_ID

    def test_invalid_designation_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(designation_id="not-a-uuid")

    def test_invalid_department_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(department_id="not-a-uuid")

    # ── optional fields ────────────────────────────────────────────────────────
    def test_manager_id_optional_none(self):
        r = self._valid()
        assert r.manager_id is None

    def test_manager_id_provided(self):
        r = self._valid(manager_id=MGR_ID)
        assert r.manager_id == MGR_ID

    def test_invalid_manager_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(manager_id="not-a-uuid")

    def test_date_of_birth_optional_none(self):
        r = self._valid()
        assert r.date_of_birth is None

    def test_date_of_birth_provided(self):
        r = self._valid(date_of_birth=date(1990, 6, 15))
        assert r.date_of_birth == date(1990, 6, 15)

    def test_date_of_birth_from_string(self):
        r = self._valid(date_of_birth="1990-06-15")
        assert r.date_of_birth == date(1990, 6, 15)

    def test_invalid_date_raises(self):
        with pytest.raises(ValidationError):
            self._valid(date_of_birth="not-a-date")

    def test_all_optional_fields_together(self):
        r = self._valid(manager_id=MGR_ID, date_of_birth=date(1985, 3, 20))
        assert r.manager_id    == MGR_ID
        assert r.date_of_birth == date(1985, 3, 20)


# ─────────────────────────────────────────────────────────────────────────────
# LoginRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginRequest:
    def _valid(self, **overrides):
        base = dict(username="john.doe", password="anypassword")
        base.update(overrides)
        return LoginRequest(**base)

    def test_valid(self):
        r = self._valid()
        assert r.username == "john.doe"
        assert r.password == "anypassword"

    def test_username_normalised_to_lowercase(self):
        """ERR-437: login must be case-insensitive."""
        r = self._valid(username="JOHN.DOE@EXAMPLE.COM")
        assert r.username == "john.doe@example.com"

    def test_username_stripped(self):
        r = self._valid(username="  john.doe  ")
        assert r.username == "john.doe"

    def test_username_uppercase_stripped_and_lowercased(self):
        r = self._valid(username="  ADMIN@COMPANY.COM  ")
        assert r.username == "admin@company.com"

    def test_email_as_username_accepted(self):
        r = self._valid(username="user@email.com")
        assert r.username == "user@email.com"

    def test_password_field_present(self):
        r = self._valid(password="s3cr3t")
        assert r.password == "s3cr3t"

    def test_empty_username_accepted_by_schema(self):
        # Schema itself has no min-length; business logic handles it
        r = self._valid(username="")
        assert r.username == ""

    def test_empty_password_accepted_by_schema(self):
        r = self._valid(password="")
        assert r.password == ""

    def test_special_chars_in_username(self):
        r = self._valid(username="user+tag@domain.io")
        assert r.username == "user+tag@domain.io"


# ─────────────────────────────────────────────────────────────────────────────
# RefreshRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshRequest:
    def test_valid(self):
        r = RefreshRequest(refresh_token="token-abc-123")
        assert r.refresh_token == "token-abc-123"

    def test_empty_token_accepted_by_schema(self):
        # Schema only requires the field to be present
        r = RefreshRequest(refresh_token="")
        assert r.refresh_token == ""

    def test_long_token_accepted(self):
        long_token = "x" * 500
        r = RefreshRequest(refresh_token=long_token)
        assert r.refresh_token == long_token

    def test_composite_token_format_preserved(self):
        token = f"{uuid.uuid4()}||{'a' * 86}"
        r = RefreshRequest(refresh_token=token)
        assert "||" in r.refresh_token

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            RefreshRequest()


# ─────────────────────────────────────────────────────────────────────────────
# LogoutRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestLogoutRequest:
    def test_valid(self):
        r = LogoutRequest(refresh_token="my-refresh-token")
        assert r.refresh_token == "my-refresh-token"

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            LogoutRequest()

    def test_composite_token_preserved(self):
        token = f"{uuid.uuid4()}||{'s' * 86}"
        r = LogoutRequest(refresh_token=token)
        assert "||" in r.refresh_token


# ─────────────────────────────────────────────────────────────────────────────
# TokenValidationRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenValidationRequest:
    def test_valid(self):
        r = TokenValidationRequest(token="header.payload.signature")
        assert r.token == "header.payload.signature"

    def test_missing_token_raises(self):
        with pytest.raises(ValidationError):
            TokenValidationRequest()

    def test_empty_string_accepted_by_schema(self):
        r = TokenValidationRequest(token="")
        assert r.token == ""


# ─────────────────────────────────────────────────────────────────────────────
# ForgotPasswordRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestForgotPasswordRequest:
    def test_valid_email(self):
        r = ForgotPasswordRequest(email="user@example.com")
        assert r.email == "user@example.com"

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            ForgotPasswordRequest(email="not-an-email")

    def test_missing_email_raises(self):
        with pytest.raises(ValidationError):
            ForgotPasswordRequest()

    def test_subdomain_email_valid(self):
        r = ForgotPasswordRequest(email="user@mail.company.co.uk")
        assert "mail.company" in r.email

    def test_plus_tag_email_valid(self):
        r = ForgotPasswordRequest(email="user+tag@example.com")
        assert r.email == "user+tag@example.com"


# ─────────────────────────────────────────────────────────────────────────────
# ResetPasswordRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestResetPasswordRequest:
    def _valid(self, **overrides):
        base = dict(token="reset-token-xyz", new_password="NewSecure1!")
        base.update(overrides)
        return ResetPasswordRequest(**base)

    def test_valid(self):
        r = self._valid()
        assert r.token        == "reset-token-xyz"
        assert r.new_password == "NewSecure1!"

    def test_missing_token_raises(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(new_password="NewSecure1!")

    def test_missing_new_password_raises(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest(token="tok")

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            ResetPasswordRequest()

    def test_long_token_ok(self):
        r = self._valid(token="t" * 200)
        assert len(r.token) == 200


# ─────────────────────────────────────────────────────────────────────────────
# EmployeeResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestEmployeeResponse:
    def _make(self, **overrides):
        base = dict(
            employee_id=EMP_ID,
            username="john.doe",
            email="john.doe@example.com",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
        )
        base.update(overrides)
        return EmployeeResponse(**base)

    def test_valid_full(self):
        r = self._make()
        assert r.employee_id == EMP_ID
        assert r.username    == "john.doe"

    def test_designation_id_optional(self):
        r = self._make(designation_id=None)
        assert r.designation_id is None

    def test_department_id_optional(self):
        r = self._make(department_id=None)
        assert r.department_id is None

    def test_from_attributes_compatible(self):
        # Verifies model_config from_attributes=True works
        obj = MagicMock()
        obj.employee_id    = EMP_ID
        obj.username       = "jane"
        obj.email          = "jane@example.com"
        obj.designation_id = DESIG_ID
        obj.department_id  = DEPT_ID
        r = EmployeeResponse.model_validate(obj)
        assert r.username == "jane"

    def test_all_uuids_preserved(self):
        r = self._make()
        assert r.designation_id == DESIG_ID
        assert r.department_id  == DEPT_ID

    def test_missing_employee_id_raises(self):
        with pytest.raises(ValidationError):
            EmployeeResponse(username="x", email="x@x.com")


# ─────────────────────────────────────────────────────────────────────────────
# TokenResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenResponse:
    def _employee(self):
        return {
            "employee_id": EMP_ID,
            "username":    "john.doe",
            "email":       "john.doe@example.com",
        }

    def _make(self, **overrides):
        base = dict(
            access_token="header.payload.sig",
            refresh_token="refresh-token-value",
            expires_in=1800,
            employee=self._employee(),
        )
        base.update(overrides)
        return TokenResponse(**base)

    def test_valid(self):
        r = self._make()
        assert r.access_token  == "header.payload.sig"
        assert r.refresh_token == "refresh-token-value"

    def test_token_type_default_bearer(self):
        r = self._make()
        assert r.token_type == "Bearer"

    def test_expires_in_stored(self):
        r = self._make(expires_in=3600)
        assert r.expires_in == 3600

    def test_employee_nested(self):
        r = self._make()
        assert r.employee.email == "john.doe@example.com"

    def test_missing_access_token_raises(self):
        with pytest.raises(ValidationError):
            TokenResponse(refresh_token="r", expires_in=1800, employee=self._employee())

    def test_missing_employee_raises(self):
        with pytest.raises(ValidationError):
            TokenResponse(access_token="a", refresh_token="r", expires_in=1800)


# ─────────────────────────────────────────────────────────────────────────────
# TokenValidationResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenValidationResponse:
    def test_valid_true(self):
        r = TokenValidationResponse(
            valid=True,
            user_id=str(EMP_ID),
            email="u@example.com",
            roles=["EMPLOYEE"],
            department_id=str(DEPT_ID),
        )
        assert r.valid is True
        assert r.error is None

    def test_valid_false_with_error(self):
        r = TokenValidationResponse(valid=False, error="Invalid or expired token")
        assert r.valid is False
        assert r.error == "Invalid or expired token"

    def test_all_fields_optional_except_valid(self):
        r = TokenValidationResponse(valid=False)
        assert r.user_id      is None
        assert r.email        is None
        assert r.roles        is None
        assert r.department_id is None

    def test_roles_list(self):
        r = TokenValidationResponse(valid=True, roles=["MANAGER", "HR_ADMIN"])
        assert "MANAGER" in r.roles

    def test_missing_valid_raises(self):
        with pytest.raises(ValidationError):
            TokenValidationResponse()


# ─────────────────────────────────────────────────────────────────────────────
# ForgotPasswordResponse / ResetPasswordResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestForgotPasswordResponse:
    def test_valid(self):
        r = ForgotPasswordResponse(message="Email sent")
        assert r.message == "Email sent"

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ForgotPasswordResponse()

    def test_long_message_accepted(self):
        msg = "x" * 1000
        r = ForgotPasswordResponse(message=msg)
        assert len(r.message) == 1000


class TestResetPasswordResponse:
    def test_valid(self):
        r = ResetPasswordResponse(message="Password reset successful")
        assert "reset" in r.message.lower()

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            ResetPasswordResponse()