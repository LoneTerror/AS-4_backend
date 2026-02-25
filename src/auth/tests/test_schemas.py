"""
Tests for src/auth/schemas.py
Covers: all Pydantic request/response models — validation, defaults, constraints
"""

import pytest
from uuid import UUID, uuid4
from pydantic import ValidationError

from src.auth.schemas import (
    SignUpRequest,
    LoginRequest,
    RefreshRequest,
    LogoutRequest,
    TokenValidationRequest,
    TokenResponse,
    TokenValidationResponse,
    EmployeeResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)


EMP_ID = uuid4()
DESIG_ID = uuid4()
DEPT_ID = uuid4()
MANAGER_ID = uuid4()


# ---------------------------------------------------------------------------
# SignUpRequest
# ---------------------------------------------------------------------------

class TestSignUpRequest:

    def test_valid_full_payload(self):
        req = SignUpRequest(
            username="jdoe",
            email="jdoe@example.com",
            password="Secret123",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
            manager_id=MANAGER_ID,
        )
        assert req.username == "jdoe"
        assert req.manager_id == MANAGER_ID

    def test_manager_id_optional_defaults_none(self):
        req = SignUpRequest(
            username="jdoe",
            email="jdoe@example.com",
            password="Secret123",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
        )
        assert req.manager_id is None

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError):
            SignUpRequest(
                username="jdoe",
                email="not-an-email",
                password="Secret123",
                designation_id=DESIG_ID,
                department_id=DEPT_ID,
            )

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            SignUpRequest(
                username="jdoe",
                email="jdoe@example.com",
                # password missing
                designation_id=DESIG_ID,
                department_id=DEPT_ID,
            )

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValidationError):
            SignUpRequest(
                username="jdoe",
                email="jdoe@example.com",
                password="Secret123",
                designation_id="not-a-uuid",
                department_id=DEPT_ID,
            )


# ---------------------------------------------------------------------------
# LoginRequest
# ---------------------------------------------------------------------------

class TestLoginRequest:

    def test_valid_login(self):
        req = LoginRequest(username="jdoe", password="pass")
        assert req.username == "jdoe"

    def test_missing_password_raises(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="jdoe")

    def test_accepts_email_as_username(self):
        req = LoginRequest(username="jdoe@example.com", password="pass")
        assert "@" in req.username


# ---------------------------------------------------------------------------
# RefreshRequest / LogoutRequest
# ---------------------------------------------------------------------------

class TestRefreshAndLogoutRequest:

    def test_refresh_request(self):
        req = RefreshRequest(refresh_token="sometoken123")
        assert req.refresh_token == "sometoken123"

    def test_logout_request(self):
        req = LogoutRequest(refresh_token="sometoken123")
        assert req.refresh_token == "sometoken123"

    def test_missing_token_raises(self):
        with pytest.raises(ValidationError):
            RefreshRequest()


# ---------------------------------------------------------------------------
# TokenValidationRequest
# ---------------------------------------------------------------------------

class TestTokenValidationRequest:

    def test_valid(self):
        req = TokenValidationRequest(token="jwt.token.here")
        assert req.token == "jwt.token.here"


# ---------------------------------------------------------------------------
# EmployeeResponse
# ---------------------------------------------------------------------------

class TestEmployeeResponse:

    def test_full_employee_response(self):
        resp = EmployeeResponse(
            employee_id=EMP_ID,
            username="jdoe",
            email="jdoe@example.com",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
        )
        assert resp.employee_id == EMP_ID

    def test_optional_ids_default_none(self):
        resp = EmployeeResponse(
            employee_id=EMP_ID,
            username="jdoe",
            email="jdoe@example.com",
        )
        assert resp.designation_id is None
        assert resp.department_id is None

    def test_from_attributes_mode_enabled(self):
        # Simulates ORM model
        class FakeOrm:
            employee_id = EMP_ID
            username = "jdoe"
            email = "jdoe@example.com"
            designation_id = DESIG_ID
            department_id = DEPT_ID

        resp = EmployeeResponse.model_validate(FakeOrm())
        assert resp.username == "jdoe"


# ---------------------------------------------------------------------------
# TokenResponse
# ---------------------------------------------------------------------------

class TestTokenResponse:

    def test_default_token_type_is_bearer(self):
        emp = EmployeeResponse(
            employee_id=EMP_ID,
            username="jdoe",
            email="jdoe@example.com",
        )
        resp = TokenResponse(
            access_token="access",
            refresh_token="refresh",
            expires_in=3600,
            employee=emp,
        )
        assert resp.token_type == "Bearer"


# ---------------------------------------------------------------------------
# TokenValidationResponse
# ---------------------------------------------------------------------------

class TestTokenValidationResponse:

    def test_valid_response(self):
        resp = TokenValidationResponse(
            valid=True,
            user_id="u1",
            email="u@x.com",
            roles=["HR_ADMIN"],
            department_id="d1",
        )
        assert resp.valid is True

    def test_invalid_response_with_error(self):
        resp = TokenValidationResponse(valid=False, error="Token expired")
        assert resp.valid is False
        assert resp.error == "Token expired"
        assert resp.user_id is None

    def test_all_fields_optional_except_valid(self):
        resp = TokenValidationResponse(valid=True)
        assert resp.roles is None


# ---------------------------------------------------------------------------
# ForgotPassword / ResetPassword
# ---------------------------------------------------------------------------

class TestPasswordResetSchemas:

    def test_forgot_password_request(self):
        req = ForgotPasswordRequest(email="user@test.com")
        assert req.email == "user@test.com"

    def test_forgot_password_invalid_email(self):
        with pytest.raises(ValidationError):
            ForgotPasswordRequest(email="notanemail")

    def test_forgot_password_response(self):
        resp = ForgotPasswordResponse(message="Check your email")
        assert "email" in resp.message.lower()

    def test_reset_password_request(self):
        req = ResetPasswordRequest(token="reset-token-abc", new_password="NewPass123")
        assert req.token == "reset-token-abc"

    def test_reset_password_response(self):
        resp = ResetPasswordResponse(message="Password reset successful")
        assert resp.message
