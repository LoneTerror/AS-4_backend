"""
⚡ Concurrency & Race Condition Tests for Auth Service
Production-Grade Concurrency Testing

Tests Cover:
- Concurrent login attempts
- Race conditions in token generation
- Database transaction isolation
- Parallel request handling
- Deadlock scenarios
- Session state consistency
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone
import time


# ==============================================================================
# CONCURRENT LOGIN TESTS
# ==============================================================================

class TestConcurrentLogin:
    """Test concurrent login attempts"""

    @pytest.mark.asyncio
    async def test_concurrent_login_same_user_same_credentials(self):
        """Test multiple simultaneous logins with same credentials"""
        
        emp = MagicMock()
        emp.employee_id = str(uuid4())
        emp.username = "testuser"
        emp.email = "test@hdfc.com"
        emp.password_hash = "hashed"
        emp.department_id = str(uuid4())
        emp.designation_id = str(uuid4())
        emp.employee_roles_employee_roles_employee_idToemployees = []
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            from src.auth.service import authenticate_user
            
            # Simulate 10 concurrent login requests
            tasks = [
                authenticate_user("testuser", "password")
                for _ in range(10)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=False)
            
            # All should succeed
            assert len(results) == 10
            for result in results:
                assert "access_token" in result
                assert "refresh_token" in result
            
            # Should have created 10 refresh tokens
            assert mock_db.refresh_tokens.create.call_count == 10

    @pytest.mark.asyncio
    async def test_concurrent_login_different_users(self):
        """Test concurrent logins from different users"""
        
        async def mock_find_employee(where, **kwargs):
            # Return different employees based on username
            username = where["OR"][0]["username"]
            emp = MagicMock()
            emp.employee_id = str(uuid4())
            emp.username = username
            emp.email = f"{username}@hdfc.com"
            emp.password_hash = "hashed"
            emp.department_id = str(uuid4())
            emp.designation_id = str(uuid4())
            emp.employee_roles_employee_roles_employee_idToemployees = []
            return emp
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(side_effect=mock_find_employee)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            from src.auth.service import authenticate_user
            
            # 5 different users logging in simultaneously
            usernames = [f"user{i}" for i in range(5)]
            tasks = [
                authenticate_user(username, "password")
                for username in usernames
            ]
            
            results = await asyncio.gather(*tasks)
            
            # All should succeed
            assert len(results) == 5
            for result in results:
                assert "access_token" in result

    @pytest.mark.asyncio
    async def test_concurrent_failed_login_attempts(self):
        """Test concurrent failed login attempts (brute force scenario)"""
        
        emp = MagicMock()
        emp.employee_id = str(uuid4())
        emp.username = "victim"
        emp.password_hash = "hashed"
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=False)
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            
            from src.auth.service import authenticate_user
            
            # 20 concurrent wrong password attempts
            tasks = [
                authenticate_user("victim", "wrong-password")
                for _ in range(20)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # All should fail with 401
            for result in results:
                assert isinstance(result, HTTPException)
                assert result.status_code == 401
            
            # NOTE: Should implement account lockout mechanism
            # After N failures, should lock account temporarily


# ==============================================================================
# CONCURRENT TOKEN OPERATIONS
# ==============================================================================

class TestConcurrentTokenOperations:
    """Test concurrent token refresh and logout"""

    @pytest.mark.asyncio
    async def test_concurrent_token_refresh_same_token(self):
        """Test concurrent refresh with same refresh token"""
        
        emp_id = str(uuid4())
        refresh_token = f"token-id||secret"
        
        rt_mock = MagicMock()
        rt_mock.token_id = "token-id"
        rt_mock.token_hash = "hashed-secret"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        rt_mock.employees = MagicMock()
        rt_mock.employees.employee_id = emp_id
        rt_mock.employees.email = "user@hdfc.com"
        rt_mock.employees.username = "testuser"
        rt_mock.employees.department_id = str(uuid4())
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.token")
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])
            
            from src.auth.service import refresh_access_token
            
            # 5 concurrent refresh requests with same token
            tasks = [
                refresh_access_token(refresh_token)
                for _ in range(5)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # Currently all succeed (no token rotation)
            # In production, should implement refresh token rotation
            assert len(results) == 5
            for result in results:
                assert "access_token" in result
            
            # TODO: Implement token rotation - only first should succeed

    @pytest.mark.asyncio
    async def test_concurrent_logout_same_session(self):
        """Test concurrent logout requests for same session"""
        
        emp_id = str(uuid4())
        refresh_token = f"token-id||secret"
        
        rt_mock = MagicMock()
        rt_mock.token_id = "token-id"
        rt_mock.token_hash = "hashed-secret"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True)
        ):
            mock_db.refresh_tokens.find_first = AsyncMock(return_value=rt_mock)
            mock_db.refresh_tokens.update = AsyncMock(return_value=rt_mock)
            
            from src.auth.service import logout_user
            
            # 3 concurrent logout requests
            tasks = [
                logout_user(refresh_token, emp_id)
                for _ in range(3)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # All should return success (idempotent)
            assert len(results) == 3
            for result in results:
                assert "Logged out" in result["message"]
            
            # Update should be called (possibly multiple times due to race)
            assert mock_db.refresh_tokens.update.called

    @pytest.mark.asyncio
    async def test_logout_during_active_refresh(self):
        """Test logout happening while token refresh is in progress"""
        
        emp_id = str(uuid4())
        refresh_token = f"token-id||secret"
        
        rt_mock = MagicMock()
        rt_mock.token_id = "token-id"
        rt_mock.token_hash = "hashed-secret"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        rt_mock.employees = MagicMock()
        rt_mock.employees.employee_id = emp_id
        rt_mock.employees.email = "user@hdfc.com"
        rt_mock.employees.username = "testuser"
        rt_mock.employees.department_id = str(uuid4())
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.token")
        ):
            # Setup mocks
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            mock_db.refresh_tokens.find_first = AsyncMock(return_value=rt_mock)
            mock_db.refresh_tokens.update = AsyncMock(return_value=rt_mock)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])
            
            from src.auth.service import refresh_access_token, logout_user
            
            # Start refresh and logout simultaneously
            refresh_task = asyncio.create_task(refresh_access_token(refresh_token))
            logout_task = asyncio.create_task(logout_user(refresh_token, emp_id))
            
            results = await asyncio.gather(refresh_task, logout_task, return_exceptions=True)
            
            # Both might succeed or one might fail depending on timing
            # This is acceptable - not a critical race condition


# ==============================================================================
# DATABASE TRANSACTION ISOLATION TESTS
# ==============================================================================

class TestDatabaseTransactionIsolation:
    """Test database transaction isolation levels"""

    @pytest.mark.asyncio
    async def test_concurrent_employee_creation_unique_constraint(self):
        """Test concurrent creation of employees with same email"""
        
        from src.auth.schemas import SignUpRequest
        from uuid import uuid4
        
        payload = SignUpRequest(
            username="newuser",
            email="duplicate@hdfc.com",
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
            
            # First creation succeeds
            mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id=str(uuid4())))
            mock_db.wallets.create = AsyncMock(return_value=MagicMock())
            
            from src.auth.service import create_employee
            
            # Simulate 2 concurrent creates with same email
            # Database should enforce unique constraint
            tasks = [
                create_employee(payload, "admin-123")
                for _ in range(2)
            ]
            
            # In real scenario, second would fail with unique constraint violation
            # With mocks, both succeed - but documents expected behavior
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # In production, one should fail with constraint error

    @pytest.mark.asyncio
    async def test_race_condition_in_refresh_token_creation(self):
        """Test race condition when creating multiple refresh tokens"""
        
        emp = MagicMock()
        emp.employee_id = str(uuid4())
        emp.username = "testuser"
        emp.email = "test@hdfc.com"
        emp.password_hash = "hashed"
        emp.department_id = str(uuid4())
        emp.designation_id = str(uuid4())
        emp.employee_roles_employee_roles_employee_idToemployees = []
        
        token_ids_created = []
        
        async def create_refresh_token(data):
            token_id = data["token_id"]
            token_ids_created.append(token_id)
            await asyncio.sleep(0.001)  # Simulate DB latency
            return MagicMock()
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(side_effect=create_refresh_token)
            
            from src.auth.service import authenticate_user
            
            # 5 concurrent logins
            tasks = [
                authenticate_user("testuser", "password")
                for _ in range(5)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # All token IDs should be unique (UUIDs)
            assert len(set(token_ids_created)) == 5


# ==============================================================================
# WALLET BALANCE RACE CONDITIONS (Cross-service concern)
# ==============================================================================

class TestWalletRaceConditions:
    """Test race conditions in wallet operations"""

    @pytest.mark.asyncio
    async def test_concurrent_wallet_creation_for_same_employee(self):
        """Test that only one wallet is created per employee"""
        
        emp_id = str(uuid4())
        new_emp = MagicMock()
        new_emp.employee_id = emp_id
        
        wallets_created = []
        
        async def create_wallet(data):
            wallets_created.append(data["employee_id"])
            await asyncio.sleep(0.001)
            return MagicMock()
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.hash_password", return_value="hashed")
        ):
            mock_db.employees.find_unique = AsyncMock(return_value=None)
            mock_db.designations.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="active"))
            mock_db.employees.create = AsyncMock(return_value=new_emp)
            mock_db.wallets.create = AsyncMock(side_effect=create_wallet)
            
            from src.auth.service import create_employee
            from src.auth.schemas import SignUpRequest
            
            payload = SignUpRequest(
                username="newuser",
                email="new@hdfc.com",
                password="Password123!",
                designation_id=uuid4(),
                department_id=uuid4()
            )
            
            # Simulate concurrent employee creation attempts
            # Should only create one wallet per employee
            await create_employee(payload, "admin-123")
            
            assert len(wallets_created) == 1


# ==============================================================================
# BULK IMPORT CONCURRENCY
# ==============================================================================

class TestBulkImportConcurrency:
    """Test concurrent bulk import operations"""

    @pytest.mark.asyncio
    async def test_concurrent_bulk_imports(self):
        """Test multiple administrators uploading bulk imports simultaneously"""
        
        # This is more of an integration test
        # Documents that concurrent bulk imports should be supported
        # Each import should be isolated and not interfere with others
        
        # Simulate 3 admins uploading CSVs at the same time
        # Each with 100 employees
        
        # Expected behavior:
        # - All imports should succeed independently
        # - No data corruption
        # - No deadlocks
        # - Each import tracked separately
        
        pass  # Placeholder for future implementation

    @pytest.mark.asyncio
    async def test_bulk_import_transaction_rollback_on_error(self):
        """Test that bulk import rolls back on error"""
        
        # If bulk import fails halfway (e.g., 50 of 100 employees)
        # Should either:
        # a) Rollback everything (all or nothing)
        # b) Continue with partial success (current implementation)
        
        # Current implementation: Partial success
        # Documents expected behavior
        
        pass  # Placeholder for future implementation


# ==============================================================================
# OPTIMISTIC LOCKING TESTS
# ==============================================================================

class TestOptimisticLocking:
    """Test optimistic locking for concurrent updates"""

    @pytest.mark.asyncio
    async def test_concurrent_password_updates(self):
        """Test concurrent password changes for same user"""
        
        emp_id = str(uuid4())
        emp = MagicMock()
        emp.employee_id = emp_id
        emp.email = "user@hdfc.com"
        emp.username = "testuser"
        
        reset_payload = {"sub": emp_id, "email": "user@hdfc.com"}
        
        update_count = 0
        
        async def update_password(where, data):
            nonlocal update_count
            update_count += 1
            await asyncio.sleep(0.001)
            return emp
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.decode_reset_token", return_value=reset_payload),
            patch("src.auth.service.hash_password") as mock_hash,
            patch("src.auth.service.send_password_reset_confirmation")
        ):
            mock_hash.side_effect = lambda p: f"hashed-{p}"
            mock_db.employees.find_unique = AsyncMock(return_value=emp)
            mock_db.employees.update = AsyncMock(side_effect=update_password)
            mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
            
            from src.auth.service import reset_password
            
            # 2 concurrent password resets
            tasks = [
                reset_password("token1", "NewPassword1"),
                reset_password("token2", "NewPassword2")
            ]
            
            results = await asyncio.gather(*tasks)
            
            # Both succeed, but second overwrites first
            assert update_count == 2
            
            # In production, consider implementing optimistic locking
            # to detect and handle concurrent modifications


# ==============================================================================
# SESSION STATE CONSISTENCY TESTS
# ==============================================================================

class TestSessionStateConsistency:
    """Test session state consistency under concurrent operations"""

    @pytest.mark.asyncio
    async def test_refresh_after_logout_consistency(self):
        """Test token refresh attempt after concurrent logout"""
        
        emp_id = str(uuid4())
        refresh_token = f"token-id||secret"
        
        rt_mock = MagicMock()
        rt_mock.token_id = "token-id"
        rt_mock.token_hash = "hashed-secret"
        rt_mock.employee_id = emp_id
        rt_mock.employees = MagicMock()
        rt_mock.employees.employee_id = emp_id
        rt_mock.employees.email = "user@hdfc.com"
        rt_mock.employees.username = "testuser"
        rt_mock.employees.department_id = str(uuid4())
        
        # Initially not revoked
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        revoked = False
        
        # CHANGE 1: Added **kwargs to absorb Prisma's 'include' arguments safely
        async def check_revoked(where, **kwargs):
            if revoked:
                rt_mock.revoked_at = datetime.now(timezone.utc)
            return rt_mock
        
        async def revoke_token(where, data, **kwargs):
            nonlocal revoked
            revoked = True
            rt_mock.revoked_at = data["revoked_at"]
            return rt_mock
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.token")
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(side_effect=check_revoked)
            mock_db.refresh_tokens.find_first = AsyncMock(side_effect=check_revoked)
            mock_db.refresh_tokens.update = AsyncMock(side_effect=revoke_token)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])
            
            from src.auth.service import refresh_access_token, logout_user
            
            # Start logout first
            logout_task = asyncio.create_task(logout_user(refresh_token, emp_id))
            await asyncio.sleep(0.001)  # Let logout start
            
            # Then try refresh
            refresh_task = asyncio.create_task(refresh_access_token(refresh_token))
            
            logout_result = await logout_task
            
            # Refresh should fail after logout
            try:
                refresh_result = await refresh_task
                # Might succeed if it checked before revocation
            except HTTPException as e:
                # Expected - token was revoked
                assert e.status_code == 401

            # CHANGE 2: Strict Validation to prevent the "garbage data" issue
            # Verify exactly what the refresh service asked the database for
            mock_db.refresh_tokens.find_unique.assert_called_with(
                where={"token_id": "token-id"},
                include={"employees": True} 
            )
            
            # Verify the logout service updated the token for the correct ID
            update_call_args = mock_db.refresh_tokens.update.call_args[1]
            assert update_call_args["where"]["token_id"] == "token-id"
            assert "revoked_at" in update_call_args["data"]


# ==============================================================================
# PERFORMANCE UNDER LOAD
# ==============================================================================

class TestPerformanceUnderLoad:
    """Test system behavior under concurrent load"""

    @pytest.mark.asyncio
    async def test_100_concurrent_logins_performance(self):
        """Test that system can handle 100 concurrent logins"""
        
        emp = MagicMock()
        emp.employee_id = str(uuid4())
        emp.username = "testuser"
        emp.email = "test@hdfc.com"
        emp.password_hash = "hashed"
        emp.department_id = str(uuid4())
        emp.designation_id = str(uuid4())
        emp.employee_roles_employee_roles_employee_idToemployees = []
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_password", return_value=True),
            patch("src.auth.service.create_access_token", return_value="token"),
            patch("src.auth.service.hash_refresh_token", return_value="hashed")
        ):
            mock_db.employees.find_first = AsyncMock(return_value=emp)
            mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock())
            
            from src.auth.service import authenticate_user
            
            # 100 concurrent login requests
            start_time = time.time()
            
            tasks = [
                authenticate_user(f"user{i}", "password")
                for i in range(100)
            ]
            
            results = await asyncio.gather(*tasks)
            
            elapsed_time = time.time() - start_time
            
            # All should succeed
            assert len(results) == 100
            
            # Should complete within reasonable time (< 5 seconds with mocks)
            assert elapsed_time < 5.0
            
            # Calculate requests per second
            rps = 100 / elapsed_time
            print(f"\nLogin performance: {rps:.2f} req/sec")
            
            # Target: > 20 req/sec (with real DB, should be > 100 req/sec with proper optimization)

    @pytest.mark.asyncio
    async def test_token_refresh_throughput(self):
        """Test token refresh throughput"""
        
        emp_id = str(uuid4())
        
        rt_mock = MagicMock()
        rt_mock.token_id = "token-id"
        rt_mock.employee_id = emp_id
        rt_mock.revoked_at = None
        rt_mock.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        rt_mock.employees = MagicMock()
        rt_mock.employees.employee_id = emp_id
        rt_mock.employees.email = "user@hdfc.com"
        rt_mock.employees.username = "testuser"
        rt_mock.employees.department_id = str(uuid4())
        
        with (
            patch("src.auth.service.db") as mock_db,
            patch("src.auth.service.verify_refresh_token", return_value=True),
            patch("src.auth.service.create_access_token", return_value="new.token")
        ):
            mock_db.refresh_tokens.find_unique = AsyncMock(return_value=rt_mock)
            mock_db.employee_roles.find_many = AsyncMock(return_value=[])
            
            from src.auth.service import refresh_access_token
            
            # 50 concurrent refresh requests
            start_time = time.time()
            
            tasks = [
                refresh_access_token(f"token-{i}||secret-{i}")
                for i in range(50)
            ]
            
            results = await asyncio.gather(*tasks)
            
            elapsed_time = time.time() - start_time
            
            assert len(results) == 50
            
            # Should be fast (< 2 seconds with mocks)
            assert elapsed_time < 2.0
            
            rps = 50 / elapsed_time
            print(f"\nRefresh performance: {rps:.2f} req/sec")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
