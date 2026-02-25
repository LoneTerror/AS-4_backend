"""
Tests for src/auth/service.py
Covers: authenticate_user, refresh_access_token, logout_user,
        create_employee, validate_token, request_password_reset, reset_password
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now():
    return datetime.now(timezone.utc)


def _make_employee(
    employee_id=None,
    username="jdoe",
    email="jdoe@example.com",
    department_id=None,
    designation_id=None,
    roles=None,
):
    emp = MagicMock()
    emp.employee_id = str(employee_id or uuid4())
    emp.username = username
    emp.email = email
    emp.department_id = str(department_id or uuid4())
    emp.designation_id = str(designation_id or uuid4())
    emp.password_hash = "hashed"

    # Build roles relation
    role_list = roles or ["EMPLOYEE"]
    emp_role_objects = []
    for r in role_list:
        er = MagicMock()
        er.roles = MagicMock()
        er.roles.role_code = r
        emp_role_objects.append(er)
    emp.employee_roles_employee_roles_employee_idToemployees = emp_role_objects

    return emp


def _make_refresh_token(employee_id, expired=False, revoked=False, token_hash="hashed-secret"):
    rt = MagicMock()
    rt.token_id = str(uuid4())
    rt.token_hash = token_hash
    rt.employee_id = employee_id
    rt.revoked_at = _utc_now() if revoked else None
    rt.expires_at = (_utc_now() - timedelta(days=1)) if expired else (_utc_now() + timedelta(days=7))
    rt.employees = _make_employee(employee_id=employee_id)
    return rt


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------

class TestValidateToken:

    @pytest.mark.asyncio
    async def test_valid_token_returns_user_info(self):
        payload = {
            "sub": "u1",
            "email": "u@x.com",
            "roles": ["HR_ADMIN"],
            "department_id": "d1",
        }
        with patch("src.auth.service.decode_token", return_value=payload):
            from src.auth.service import validate_token
            result = await validate_token("valid.token")

        assert result["valid"] is True
        assert result["user_id"] == "u1"
        assert result["roles"] == ["HR_ADMIN"]

    @pytest.mark.asyncio
    async def test_invalid_token_returns_invalid_response(self):
        with patch("src.auth.service.decode_token", return_value=None):
            from src.auth.service import validate_token
            result = await validate_token("bad.token")

        assert result["valid"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------

class TestAuthenticateUser:

    @pytest.mark.asyncio
    async def test_successful_login(self):
        emp = _make_employee(roles=["EMPLOYEE"])

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="access.token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed-rt"),
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())

            from src.auth.service import authenticate_user
            result = await authenticate_user("jdoe", "password")

        assert result["access_token"] == "access.token"
        assert "refresh_token" in result
        assert result["employee"]["username"] == "jdoe"

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_first = AsyncMock(return_value=None)

            from src.auth.service import authenticate_user

            with pytest.raises(HTTPException) as exc:
                await authenticate_user("nobody", "pass")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_password_raises_401(self):
        emp = _make_employee()

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=False),
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)

            from src.auth.service import authenticate_user

            with pytest.raises(HTTPException) as exc:
                await authenticate_user("jdoe", "wrongpassword")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_roles_defaults_to_employee(self):
        """If role extraction fails, fallback role EMPLOYEE should be applied."""
        emp = _make_employee()
        emp.employee_roles_employee_roles_employee_idToemployees = []  # empty roles

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="tok") as mock_create,
            patch("src.auth.service.hash_refresh_token", return_value="hashed"),
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())

            from src.auth.service import authenticate_user
            await authenticate_user("jdoe", "pass")

        call_kwargs = mock_create.call_args[0][0]
        assert call_kwargs["roles"] == ["EMPLOYEE"]

    @pytest.mark.asyncio
    async def test_refresh_token_stored_in_db(self):
        emp = _make_employee(roles=["EMPLOYEE"])

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="tok"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed"),
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())

            from src.auth.service import authenticate_user
            await authenticate_user("jdoe", "pass")

        mock_db.refresh_tokens.create.assert_called_once()


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------

class TestRefreshAccessToken:

    @pytest.mark.asyncio
    async def test_successful_refresh(self):
        emp_id = str(uuid4())
        rt = _make_refresh_token(employee_id=emp_id)
        rt.token_hash = "hashed-secret"

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.access"),
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])

            from src.auth.service import refresh_access_token, _TOKEN_SEP
            client_token = f"token-id{_TOKEN_SEP}token-secret"

            # Patch token_id lookup to return our rt
            rt.employees = _make_employee(employee_id=emp_id)

            result = await refresh_access_token(client_token)

        assert result["access_token"] == "new.access"

    @pytest.mark.asyncio
    async def test_invalid_format_raises_401(self):
        from src.auth.service import refresh_access_token

        with pytest.raises(HTTPException) as exc:
            await refresh_access_token("no-separator-here")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_token_not_found_raises_401(self):
        with patch("src.auth.service.db") as mock_db:
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=None)

            from src.auth.service import refresh_access_token, _TOKEN_SEP

            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        emp_id = str(uuid4())
        rt = _make_refresh_token(employee_id=emp_id, expired=True)

        with patch("src.auth.service.db") as mock_db:
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt)

            from src.auth.service import refresh_access_token, _TOKEN_SEP

            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_revoked_token_raises_401(self):
        emp_id = str(uuid4())
        rt = _make_refresh_token(employee_id=emp_id, revoked=True)

        with patch("src.auth.service.db") as mock_db:
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt)

            from src.auth.service import refresh_access_token, _TOKEN_SEP

            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")

        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_roles_falls_back_to_employee(self):
        emp_id = str(uuid4())
        rt = _make_refresh_token(employee_id=emp_id)
        rt.employees = _make_employee(employee_id=emp_id)

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="tok") as mock_create,
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])  # empty roles

            from src.auth.service import refresh_access_token, _TOKEN_SEP
            await refresh_access_token(f"id{_TOKEN_SEP}secret")

        call_kwargs = mock_create.call_args[0][0]
        assert call_kwargs["roles"] == ["EMPLOYEE"]


# ---------------------------------------------------------------------------
# logout_user
# ---------------------------------------------------------------------------

class TestLogoutUser:

    @pytest.mark.asyncio
    async def test_successful_logout_revokes_token(self):
        emp_id = str(uuid4())
        rt = _make_refresh_token(employee_id=emp_id)

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
        ):
            mock_db.refresh_tokens.find_first = AsyncMock(return_value=rt)
            mock_db.refresh_tokens.update = AsyncMock(return_value=rt)

            from src.auth.service import logout_user, _TOKEN_SEP
            result = await logout_user(f"{rt.token_id}{_TOKEN_SEP}secret", emp_id)

        assert result["message"] == "Logged out successfully"
        mock_db.refresh_tokens.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_format_returns_gracefully(self):
        from src.auth.service import logout_user

        result = await logout_user("no-separator", "user-id")
        assert "logged out" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_token_not_belonging_to_user_skips_revocation(self):
        """If token is not found for that user, revocation is skipped — no error."""
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
        ):
            mock_db.refresh_tokens.find_first = AsyncMock(return_value=None)
            mock_db.refresh_tokens.update = AsyncMock()

            from src.auth.service import logout_user, _TOKEN_SEP
            result = await logout_user(f"id{_TOKEN_SEP}secret", "user-id")

        assert result["message"] == "Logged out successfully"
        mock_db.refresh_tokens.update.assert_not_called()


# ---------------------------------------------------------------------------
# create_employee
# ---------------------------------------------------------------------------

class TestCreateEmployee:

    def _mock_signup_payload(self, manager_id=None):
        from src.auth.schemas import SignUpRequest
        return SignUpRequest(
            username="newuser",
            email="new@example.com",
            password="Pass123",
            designation_id=uuid4(),
            department_id=uuid4(),
            manager_id=manager_id,
        )

    @pytest.mark.asyncio
    async def test_creates_employee_and_wallet(self):
        payload = self._mock_signup_payload()
        new_emp = _make_employee(username="newuser", email="new@example.com")
        new_emp.manager_id = None

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed"),
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)  # manager check
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            status_mock = MagicMock()
            status_mock.status_id = "status-active"
            mock_db.status_master.find_first = AsyncMock(return_value=status_mock)
            mock_db.employees.create = AsyncMock(return_value=new_emp)
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())

            from src.auth.service import create_employee
            result = await create_employee(payload, "admin-id")

        mock_db.wallets.create.assert_called_once()
        assert result.username == "newuser"

    @pytest.mark.asyncio
    async def test_invalid_designation_raises_400(self):
        payload = self._mock_signup_payload()

        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=None)

            from src.auth.service import create_employee

            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin-id")

        assert exc.value.status_code == 400
        assert "Designation" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_department_raises_400(self):
        payload = self._mock_signup_payload()

        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=None)

            from src.auth.service import create_employee

            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin-id")

        assert exc.value.status_code == 400
        assert "Department" in exc.value.detail

    @pytest.mark.asyncio
    async def test_invalid_manager_raises_400(self):
        manager_id = uuid4()
        payload = self._mock_signup_payload(manager_id=manager_id)

        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_unique = AsyncMock(return_value=None)  # manager not found

            from src.auth.service import create_employee

            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin-id")

        assert exc.value.status_code == 400
        assert "Manager" in exc.value.detail

    @pytest.mark.asyncio
    async def test_missing_active_status_raises_500(self):
        payload = self._mock_signup_payload()

        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(return_value=None)

            from src.auth.service import create_employee

            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin-id")

        assert exc.value.status_code == 500


# ---------------------------------------------------------------------------
# request_password_reset
# ---------------------------------------------------------------------------

class TestRequestPasswordReset:

    @pytest.mark.asyncio
    async def test_existing_user_triggers_email(self):
        emp = _make_employee()

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.create_reset_token", return_value="reset-tok"),
            patch("src.auth.service.send_password_reset_email") as mock_send,
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)

            from src.auth.service import request_password_reset
            result = await request_password_reset(emp.email)

        mock_send.assert_called_once()
        assert "message" in result

    @pytest.mark.asyncio
    async def test_non_existent_email_still_returns_success(self):
        """Prevents email enumeration — always returns success."""
        with patch("src.auth.service.db") as mock_db:
            mock_db.employees.find_unique = AsyncMock(return_value=None)

            from src.auth.service import request_password_reset
            result = await request_password_reset("noone@example.com")

        assert "message" in result

    @pytest.mark.asyncio
    async def test_email_send_failure_does_not_raise(self):
        emp = _make_employee()

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.create_reset_token", return_value="tok"),
            patch("src.auth.service.send_password_reset_email", side_effect=Exception("SMTP error")),
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)

            from src.auth.service import request_password_reset
            result = await request_password_reset(emp.email)  # should not raise

        assert "message" in result


# ---------------------------------------------------------------------------
# reset_password
# ---------------------------------------------------------------------------

class TestResetPassword:

    @pytest.mark.asyncio
    async def test_successful_password_reset(self):
        emp = _make_employee()
        payload = {"sub": emp.employee_id, "email": emp.email}

        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.decode_reset_token", return_value=payload),
            patch("src.auth.service.hash_password", return_value="newhash"),
            patch("src.auth.service.send_password_reset_confirmation"),
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)
            mock_db.employees.update = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)

            from src.auth.service import reset_password
            result = await reset_password("valid-token", "NewPass123")

        assert "successful" in result["message"].lower()
        mock_db.refresh_tokens.update_many.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_reset_token_raises_400(self):
        with patch("src.auth.service.decode_reset_token", return_value=None):
            from src.auth.service import reset_password

            with pytest.raises(HTTPException) as exc:
                await reset_password("bad-token", "NewPass123")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_user_not_found_raises_400(self):
        payload = {"sub": "uid", "email": "u@x.com"}

        with (
            patch("src.auth.service.decode_reset_token", return_value=payload),
            patch("src.auth.service.db") as mock_db,
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)

            from src.auth.service import reset_password

            with pytest.raises(HTTPException) as exc:
                await reset_password("token", "NewPass123")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_email_mismatch_raises_400(self):
        emp = _make_employee(email="real@example.com")
        payload = {"sub": emp.employee_id, "email": "different@example.com"}

        with (
            patch("src.auth.service.decode_reset_token", return_value=payload),
            patch("src.auth.service.db") as mock_db,
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)

            from src.auth.service import reset_password

            with pytest.raises(HTTPException) as exc:
                await reset_password("token", "NewPass123")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_all_refresh_tokens_revoked_on_reset(self):
        emp = _make_employee()
        payload = {"sub": emp.employee_id, "email": emp.email}

        with (
            patch("src.auth.service.decode_reset_token", return_value=payload),
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed"),
            patch("src.auth.service.send_password_reset_confirmation"),
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)
            mock_db.employees.update = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)

            from src.auth.service import reset_password
            await reset_password("token", "NewPass123")

        mock_db.refresh_tokens.update_many.assert_called_once()
