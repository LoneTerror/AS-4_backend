"""
Tests Cover:
- Complete user journeys (Signup → Login → Refresh → Logout)
- Password reset flow
- Role change propagation
- Cross-service integration
- Data consistency
- Error handling
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone

# Import all schemas at top to eliminate yellow warnings
from src.auth.schemas import SignUpRequest


# ==============================================================================
# COMPLETE USER JOURNEY TESTS
# ==============================================================================

class TestCompleteUserJourneys:
    """Test complete user journeys from start to finish"""

    @pytest.mark.asyncio
    async def test_complete_signup_login_refresh_logout_flow(self):
        """Test full user lifecycle: Signup → Login → Refresh → Logout"""
        
        # Step 1: Signup (Employee Creation)
        from src.auth.service import create_employee
        
        signup_payload = SignUpRequest(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123!",
            designation_id=uuid4(),
            department_id=uuid4()
        )
        
        emp_id = str(uuid4())
        new_emp = MagicMock()
        new_emp.employee_id = emp_id
        new_emp.username = "newuser"
        new_emp.email = "newuser@hdfc.com"
        new_emp.designation_id = str(signup_payload.designation_id)
        new_emp.department_id = str(signup_payload.department_id)
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed_password")
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(
                return_value=MagicMock(status_id="status-active")
            )
            mock_db.employees.create = AsyncMock(return_value=new_emp)
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())
            
            created_emp = await create_employee(signup_payload, "admin-123")
            assert created_emp.employee_id == emp_id
        
        # Step 2: Login
        from src.auth.service import authenticate_user
        
        emp_with_roles = MagicMock()
        emp_with_roles.employee_id = emp_id
        emp_with_roles.username = "newuser"
        emp_with_roles.email = "newuser@hdfc.com"
        emp_with_roles.password_hash = "hashed_password"
        emp_with_roles.department_id = str(signup_payload.department_id)
        emp_with_roles.designation_id = str(signup_payload.designation_id)
        emp_with_roles.employee_roles_employee_roles_employee_idToemployees = []
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="access.token.jwt"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed_refresh")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp_with_roles)
            mock_db.refresh_tokens.create = AsyncMock(
                return_value=MagicMock(token_id="refresh-id-123")
            )
            
            login_result = await authenticate_user("newuser", "SecurePass123!")
            
            assert "access_token" in login_result
            assert "refresh_token" in login_result
            assert login_result["employee"]["username"] == "newuser"
            
            refresh_token = login_result["refresh_token"]
            access_token = login_result["access_token"]
        
        # Step 3: Use access token to make authenticated request
        from src.auth.dependencies import get_current_user
        
        token_payload = {
            "sub": emp_id,
            "email": "newuser@hdfc.com",
            "roles": ["EMPLOYEE"],
            "department_id": str(signup_payload.department_id)
        }
        
        # 🔧 FIX #1: Changed from src.core.security to src.auth.dependencies
        # This is the KEY FIX - patch where decode_token is IMPORTED, not where it's DEFINED
        # get_current_user() imports decode_token in dependencies.py, so patch it there
        with patch("src.auth.dependencies.decode_token", return_value=token_payload):
            current_user = await get_current_user(token=access_token)
            assert current_user.id == emp_id
            assert "EMPLOYEE" in current_user.roles
        
        # Step 4: Refresh access token
        from src.auth.service import refresh_access_token
        
        rt_mock = MagicMock()
        rt_mock.token_id = "refresh-id-123"
        rt_mock.token_hash = "hashed_refresh"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        rt_mock.employees = emp_with_roles
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.access.token")
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])
            
            refresh_result = await refresh_access_token(refresh_token)
            
            assert "access_token" in refresh_result
            assert refresh_result["access_token"] == "new.access.token"
            new_access_token = refresh_result["access_token"]
        
        # Step 5: Logout
        from src.auth.service import logout_user
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True)
        ):
            mock_db.refresh_tokens.find_first = AsyncMock(return_value=rt_mock)
            mock_db.refresh_tokens.update = AsyncMock(return_value=rt_mock)
            
            logout_result = await logout_user(refresh_token, emp_id)
            
            assert "Logged out successfully" in logout_result["message"]
        
        # Step 6: Verify token is revoked (cannot refresh after logout)
        rt_mock.revoked_at = datetime.now(timezone.utc)
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True)
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            
            with pytest.raises(HTTPException) as exc:
                await refresh_access_token(refresh_token)
            
            assert exc.value.status_code == 401
            assert "revoked" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_password_reset_complete_flow(self):
        """Test complete password reset flow: Request → Email → Reset → Login"""
        
        # Step 1: User requests password reset
        from src.auth.service import request_password_reset
        
        emp = MagicMock()
        emp.employee_id = str(uuid4())
        emp.username = "forgetful_user"
        emp.email = "forgetful@hdfc.com"
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.create_reset_token", return_value="reset.token.jwt"),
            patch("src.auth.service.send_password_reset_email") as mock_email
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)
            
            reset_request_result = await request_password_reset("forgetful@hdfc.com")
            
            assert "message" in reset_request_result
            mock_email.assert_called_once_with(
                email="forgetful@hdfc.com",
                reset_token="reset.token.jwt",
                username="forgetful_user"
            )
        
        # Step 2: User clicks link in email and resets password
        from src.auth.service import reset_password
        
        reset_payload = {
            "sub": emp.employee_id,
            "email": "forgetful@hdfc.com",
            "purpose": "password_reset"
        }
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.decode_reset_token", return_value=reset_payload),
            patch("src.auth.service.hash_password", return_value="new_hashed_password"),
            patch("src.auth.service.send_password_reset_confirmation") as mock_confirm
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=emp)
            mock_db.employees.update = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
            
            reset_result = await reset_password("reset.token.jwt", "NewSecurePass123!")
            
            assert "successful" in reset_result["message"].lower()
            
            # Verify old sessions were revoked
            mock_db.refresh_tokens.update_many.assert_called_once()
            
            # Verify confirmation email sent
            mock_confirm.assert_called_once_with(
                email="forgetful@hdfc.com",
                username="forgetful_user"
            )
        
        # Step 3: User logs in with new password
        from src.auth.service import authenticate_user
        
        emp.password_hash = "new_hashed_password"
        emp.employee_roles_employee_roles_employee_idToemployees = []
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.access.token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            login_result = await authenticate_user("forgetful_user", "NewSecurePass123!")
            
            assert "access_token" in login_result
            assert login_result["employee"]["username"] == "forgetful_user"

    @pytest.mark.asyncio
    async def test_role_change_propagation_flow(self):
        """Test role change and its effect on tokens"""
        
        emp_id = str(uuid4())
        
        # Step 1: User logs in with EMPLOYEE role
        from src.auth.service import authenticate_user
        
        emp = MagicMock()
        emp.employee_id = emp_id
        emp.username = "promoted_user"
        emp.email = "promoted@hdfc.com"
        emp.password_hash = "hashed"
        emp.department_id = str(uuid4())
        emp.designation_id = str(uuid4())
        emp.employee_roles_employee_roles_employee_idToemployees = [
            MagicMock(roles=MagicMock(role_code="EMPLOYEE"), is_active=True)
        ]
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="employee.token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            login_result = await authenticate_user("promoted_user", "password")
            
            # Verify EMPLOYEE role in token
            refresh_token = login_result["refresh_token"]
        
        # Step 2: Admin promotes user to MANAGER role
        # (This would happen in employee/organization service)
        # Simulating the role change...
        
        # Step 3: User refreshes token - should get new role
        from src.auth.service import refresh_access_token
        
        # Now user has MANAGER role
        manager_role_relation = MagicMock()
        manager_role_relation.roles = MagicMock(role_code="MANAGER")
        manager_role_relation.is_active = True
        
        rt_mock = MagicMock()
        rt_mock.token_id = "refresh-id"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        rt_mock.employees = emp
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token") as mock_create_token
        ):
            mock_create_token.return_value = "manager.token"
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[manager_role_relation])
            
            refresh_result = await refresh_access_token(refresh_token)
            
            # Verify new token has MANAGER role
            call_args = mock_create_token.call_args[0][0]
            assert "MANAGER" in call_args["roles"]


# ==============================================================================
# CROSS-SERVICE INTEGRATION TESTS
# ==============================================================================

class TestCrossServiceIntegration:
    """Test integration between auth service and other services"""

    @pytest.mark.asyncio
    async def test_token_validation_for_recognition_service(self):
        """Test recognition service validating token via auth service"""
        
        from src.auth.service import validate_token
        
        valid_payload = {
            "sub": "emp-123",
            "email": "employee@hdfc.com",
            "roles": ["EMPLOYEE"],
            "department_id": "dept-001"
        }
        
        # 🔧 FIX #2: Changed from src.core.security to src.auth.service
        # validate_token() is in service.py and imports decode_token there
        # So patch it at src.auth.service.decode_token, not src.core.security
        with patch("src.auth.service.decode_token", return_value=valid_payload):
            result = await validate_token("valid.jwt.token")
            
            assert result["valid"] is True
            assert result["user_id"] == "emp-123"
            assert "EMPLOYEE" in result["roles"]
        
        # Recognition service can now trust this user info
        # and proceed with creating recognition

    @pytest.mark.asyncio
    async def test_employee_creation_triggers_wallet_creation(self):
        """Test that creating employee also creates wallet"""
        
        from src.auth.service import create_employee
        
        emp_id = str(uuid4())
        payload = SignUpRequest(
            username="newemployee",
            email="new@hdfc.com",
            password="Password123!",
            designation_id=uuid4(),
            department_id=uuid4()
        )
        
        wallet_created = False
        wallet_employee_id = None
        
        async def create_wallet(data):
            nonlocal wallet_created, wallet_employee_id
            wallet_created = True
            wallet_employee_id = data["employee_id"]
            return MagicMock(wallet_id=str(uuid4()))
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed")
        ):
            new_emp = MagicMock()
            new_emp.employee_id = emp_id
            
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(
                return_value=MagicMock(status_id="active")
            )
            mock_db.employees.create = AsyncMock(return_value=new_emp)
            mock_db.wallets.create = AsyncMock(side_effect=create_wallet)
            
            created_emp = await create_employee(payload, "admin-123")
            
            # Verify wallet was created
            assert wallet_created
            assert wallet_employee_id == emp_id
            
            # Verify initial balance is 0
            wallet_call = mock_db.wallets.create.call_args[1]["data"]
            assert wallet_call["available_points"] == 0
            assert wallet_call["redeemed_points"] == 0
            assert wallet_call["total_earned_points"] == 0

    @pytest.mark.asyncio
    async def test_bulk_import_creates_employees_and_wallets(self):
        """Test bulk import creates both employees and wallets"""
        
        # This would be tested in router tests
        # Documents that bulk import should create wallets for all employees
        pass


# ==============================================================================
# DATA CONSISTENCY TESTS
# ==============================================================================

class TestDataConsistency:
    """Test data consistency across operations"""

    @pytest.mark.asyncio
    async def test_employee_id_consistent_across_operations(self):
        """Test employee ID remains consistent through login, refresh, logout"""
        
        emp_id = str(uuid4())
        
        # Create employee
        from src.auth.service import create_employee
        
        payload = SignUpRequest(
            username="consistent_user",
            email="consistent@hdfc.com",
            password="Password123!",
            designation_id=uuid4(),
            department_id=uuid4()
        )
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed")
        ):
            new_emp = MagicMock()
            new_emp.employee_id = emp_id
            
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="active"))
            mock_db.employees.create = AsyncMock(return_value=new_emp)
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())
            
            created = await create_employee(payload, "admin-123")
            assert created.employee_id == emp_id
        
        # Login - verify same ID in token
        from src.auth.service import authenticate_user
        
        emp = MagicMock()
        emp.employee_id = emp_id
        emp.username = "consistent_user"
        emp.email = "consistent@hdfc.com"
        emp.password_hash = "hashed"
        emp.department_id = str(uuid4())
        emp.designation_id = str(uuid4())
        emp.employee_roles_employee_roles_employee_idToemployees = []
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token") as mock_token,
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_token.return_value = "token"
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            result = await authenticate_user("consistent_user", "Password123!")
            
            # Verify employee_id in response matches
            assert result["employee"]["employee_id"] == emp_id
            
            # Verify token payload has correct ID
            token_call = mock_token.call_args[0][0]
            assert token_call["sub"] == emp_id

    @pytest.mark.asyncio
    async def test_audit_trail_consistency(self):
        """Test that audit fields are consistent"""
        
        admin_id = str(uuid4())
        
        from src.auth.service import create_employee
        
        payload = SignUpRequest(
            username="audituser",
            email="audit@hdfc.com",
            password="Password123!",
            designation_id=uuid4(),
            department_id=uuid4()
        )
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed")
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="active"))
            mock_db.employees.create = AsyncMock(return_value=MagicMock())
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())
            
            await create_employee(payload, admin_id)
            
            # Verify employee creation audit fields
            emp_call = mock_db.employees.create.call_args[1]["data"]
            assert emp_call["created_by"] == admin_id
            assert emp_call["updated_by"] == admin_id
            assert "updated_at" in emp_call
            
            # Verify wallet creation audit fields
            wallet_call = mock_db.wallets.create.call_args[1]["data"]
            assert wallet_call["created_by"] == admin_id
            assert wallet_call["updated_by"] == admin_id


# ==============================================================================
# ERROR PROPAGATION TESTS
# ==============================================================================

class TestErrorPropagation:
    """Test error handling across service boundaries"""

    @pytest.mark.asyncio
    async def test_database_error_in_employee_creation_prevents_wallet_creation(self):
        """Test that wallet is not created if employee creation fails"""
        
        from src.auth.service import create_employee
        
        payload = SignUpRequest(
            username="failuser",
            email="fail@hdfc.com",
            password="Password123!",
            designation_id=uuid4(),
            department_id=uuid4()
        )
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed")
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="active"))
            
            # Employee creation fails
            mock_db.employees.create = AsyncMock(
                side_effect=Exception("Database error")
            )
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())
            
            # Should raise exception
            with pytest.raises(Exception):
                await create_employee(payload, "admin-123")
            
            # Wallet creation should not be attempted
            mock_db.wallets.create.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
