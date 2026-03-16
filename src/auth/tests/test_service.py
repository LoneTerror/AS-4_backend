import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone

from src.auth import service
from src.auth.service import (
    authenticate_user,
    validate_token,
    refresh_access_token,
    logout_user,
    create_employee,
    request_password_reset,
    reset_password,
    _TOKEN_SEP
)

# Set up module path constants for easy patching
SVC = "src.auth.service"
DB = "src.auth.service.db"

@pytest.mark.asyncio
class TestAuthService:

    # ===========================================================================
    # 1. VALIDATE TOKEN
    # ===========================================================================
    async def test_validate_token_success(self):
        mock_payload = {"sub": "e1", "email": "test@test.com", "roles": ["ADMIN"], "department_id": "d1"}
        with patch(f"{SVC}.decode_token", return_value=mock_payload):
            res = await validate_token("valid.jwt.token")
            assert res["valid"] is True
            assert res["user_id"] == "e1"

    async def test_validate_token_invalid(self):
        with patch(f"{SVC}.decode_token", return_value=None):
            res = await validate_token("invalid.jwt.token")
            assert res["valid"] is False
            assert "Invalid" in res["error"]

    # ===========================================================================
    # 2. AUTHENTICATE USER
    # ===========================================================================
    async def test_authenticate_user_success(self, sample_user):
        with patch.object(service.db.employees, "find_first", AsyncMock(return_value=sample_user)), \
             patch.object(service.db.refresh_tokens, "create", AsyncMock()), \
             patch(f"{SVC}.verify_password", return_value=True), \
             patch(f"{SVC}.create_access_token", return_value="access_token"):
            
            result = await authenticate_user("testuser", "correct_pass")
            
            assert result["access_token"] == "access_token"
            assert result["employee"]["username"] == sample_user.username
            service.db.employees.find_first.assert_called_once()

    async def test_authenticate_user_not_found(self):
        with patch.object(service.db.employees, "find_first", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await authenticate_user("ghost", "pass")
            assert exc.value.status_code == 401

    async def test_authenticate_user_wrong_password(self, sample_user):
        with patch.object(service.db.employees, "find_first", AsyncMock(return_value=sample_user)), \
             patch(f"{SVC}.verify_password", return_value=False):
            with pytest.raises(HTTPException) as exc:
                await authenticate_user("testuser", "wrong_pass")
            assert exc.value.status_code == 401

    async def test_authenticate_user_fallback_roles(self):
        # Simulate a user with no roles assigned to trigger the fallback to ["EMPLOYEE"]
        mock_user = MagicMock()
        mock_user.employee_roles_employee_roles_employee_idToemployees = None
        
        with patch(f"{DB}.employees.find_first", AsyncMock(return_value=mock_user)), \
             patch(f"{DB}.refresh_tokens.create", AsyncMock()), \
             patch(f"{SVC}.verify_password", return_value=True), \
             patch(f"{SVC}.create_access_token", return_value="access_token") as mock_create_token:
            
            await authenticate_user("user", "pass")
            
            # Verify the fallback role was applied
            mock_create_token.assert_called_once()
            args, _ = mock_create_token.call_args
            assert "EMPLOYEE" in args[0]["roles"]

    # ===========================================================================
    # 3. REFRESH ACCESS TOKEN
    # ===========================================================================
    async def test_refresh_token_invalid_format(self):
        with pytest.raises(HTTPException) as exc:
            await refresh_access_token("invalid_format_without_separator")
        assert exc.value.status_code == 401

    async def test_refresh_token_not_found(self):
        with patch(f"{DB}.refresh_tokens.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")
            assert exc.value.status_code == 401

    async def test_refresh_token_expired_or_revoked(self):
        mock_token = MagicMock()
        mock_token.revoked_at = datetime.now(timezone.utc) # Revoked
        
        with patch(f"{DB}.refresh_tokens.find_unique", AsyncMock(return_value=mock_token)):
            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")
            assert exc.value.status_code == 401

    async def test_refresh_token_invalid_signature(self):
        mock_token = MagicMock()
        mock_token.revoked_at = None
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        
        with patch(f"{DB}.refresh_tokens.find_unique", AsyncMock(return_value=mock_token)), \
             patch(f"{SVC}.verify_refresh_token", return_value=False):
            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(f"id{_TOKEN_SEP}secret")
            assert exc.value.status_code == 401

    async def test_refresh_token_success(self):
        mock_token = MagicMock()
        mock_token.revoked_at = None
        mock_token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        mock_token.employees = MagicMock()
        
        mock_role_rel = MagicMock()
        mock_role_rel.is_active = True
        mock_role_rel.roles.role_code = "MANAGER"

        with patch(f"{DB}.refresh_tokens.find_unique", AsyncMock(return_value=mock_token)), \
             patch(f"{DB}.employee_roles.find_many", AsyncMock(return_value=[mock_role_rel])), \
             patch(f"{SVC}.verify_refresh_token", return_value=True), \
             patch(f"{SVC}.create_access_token", return_value="new_access_token"):
            
            res = await refresh_access_token(f"id{_TOKEN_SEP}secret")
            assert res["access_token"] == "new_access_token"

    # ===========================================================================
    # 4. LOGOUT USER
    # ===========================================================================
    async def test_logout_invalid_format(self):
        res = await logout_user("invalid", "e1")
        assert "Invalid token format" in res["message"]

    async def test_logout_success(self):
        mock_token = MagicMock()
        with patch(f"{DB}.refresh_tokens.find_first", AsyncMock(return_value=mock_token)), \
             patch(f"{SVC}.verify_refresh_token", return_value=True), \
             patch(f"{DB}.refresh_tokens.update", AsyncMock()) as mock_update:
            
            res = await logout_user(f"id{_TOKEN_SEP}secret", "e1")
            assert res["message"] == "Logged out successfully"
            mock_update.assert_called_once()

    # ===========================================================================
    # 5. CREATE EMPLOYEE
    # ===========================================================================
    async def test_create_employee_validation_failures(self):
        payload = MagicMock()
        payload.username = " test "
        payload.manager_id = "m1"
        
        # Test Manager Not Found
        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin")
            assert exc.value.status_code == 400
            assert "Manager" in exc.value.detail

    async def test_create_employee_success(self):
        payload = MagicMock()
        payload.username = "new_user"
        payload.manager_id = None
        payload.date_of_birth = datetime(1990, 1, 1).date()
        
        mock_emp = MagicMock()
        mock_emp.employee_id = "new_e1"

        with patch(f"{DB}.designations.find_unique", AsyncMock(return_value=True)), \
             patch(f"{DB}.departments.find_unique", AsyncMock(return_value=True)), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=MagicMock(status_id="s1"))), \
             patch(f"{DB}.employees.create", AsyncMock(return_value=mock_emp)), \
             patch(f"{DB}.wallets.create", AsyncMock()), \
             patch(f"{SVC}.hash_password", return_value="hashed"):
            
            res = await create_employee(payload, "admin")
            assert res.employee_id == "new_e1"

    async def test_create_employee_missing_active_status(self):
        payload = MagicMock()
        payload.manager_id = None
        with patch(f"{DB}.designations.find_unique", AsyncMock(return_value=True)), \
             patch(f"{DB}.departments.find_unique", AsyncMock(return_value=True)), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=None)): # Missing status
            
            with pytest.raises(HTTPException) as exc:
                await create_employee(payload, "admin")
            assert exc.value.status_code == 500

    # ===========================================================================
    # 6. REQUEST PASSWORD RESET
    # ===========================================================================
    async def test_request_password_reset_user_found(self):
        mock_user = MagicMock()
        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=mock_user)), \
             patch(f"{SVC}.create_reset_token", return_value="token"), \
             patch(f"{SVC}.send_password_reset_email") as mock_send:
            
            res = await request_password_reset("test@test.com")
            assert "shortly" in res["message"]
            mock_send.assert_called_once()

    async def test_request_password_reset_user_not_found(self):
        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=None)):
            res = await request_password_reset("unknown@test.com")
            # Should still return success to prevent email enumeration
            assert "shortly" in res["message"]

    # ===========================================================================
    # 7. RESET PASSWORD
    # ===========================================================================
    async def test_reset_password_invalid_token(self):
        with patch(f"{SVC}.decode_reset_token", return_value=None):
            with pytest.raises(HTTPException) as exc:
                await reset_password("bad_token", "new_pass")
            assert exc.value.status_code == 400

    async def test_reset_password_success(self):
        mock_payload = {"sub": "e1", "email": "test@test.com"}
        mock_user = MagicMock()
        mock_user.email = "test@test.com"

        with patch(f"{SVC}.decode_reset_token", return_value=mock_payload), \
             patch(f"{DB}.employees.find_unique", AsyncMock(return_value=mock_user)), \
             patch(f"{SVC}.hash_password", return_value="new_hash"), \
             patch(f"{DB}.employees.update", AsyncMock()), \
             patch(f"{DB}.refresh_tokens.update_many", AsyncMock()), \
             patch(f"{SVC}.send_password_reset_confirmation") as mock_confirm:
            
            res = await reset_password("valid_token", "new_pass")
            assert "successful" in res["message"]
            mock_confirm.assert_called_once()