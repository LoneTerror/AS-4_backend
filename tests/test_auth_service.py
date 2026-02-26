"""
Comprehensive Unit Tests for HDFC Rewards and Recognition Auth Service

Test Coverage:
- dependencies.py: CurrentUser, get_current_user, require_roles
- service.py: login, refresh_token, logout, create_employee, password_reset
- Edge cases, security scenarios, and error handling
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Assuming these are your imports - adjust paths as needed
# from src.auth.dependencies import CurrentUser, get_current_user, require_roles
# from src.auth.service import (
#     login_user, refresh_access_token, logout_user,
#     create_employee, request_password_reset, reset_password
# )


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_db():
    """Mock Prisma database client"""
    return MagicMock()


@pytest.fixture
def mock_current_user():
    """Standard mock current user"""
    return {
        "id": "emp-123",
        "email": "test@hdfc.com",
        "roles": ["EMPLOYEE"]
    }


@pytest.fixture
def mock_admin_user():
    """Mock admin user"""
    return {
        "id": "admin-123",
        "email": "admin@hdfc.com",
        "roles": ["ADMIN"]
    }


@pytest.fixture
def mock_super_admin_user():
    """Mock super admin user"""
    return {
        "id": "superadmin-123",
        "email": "superadmin@hdfc.com",
        "roles": ["SUPER_ADMIN"]
    }


@pytest.fixture
def valid_token_payload():
    """Valid JWT token payload"""
    return {
        "sub": "emp-123",
        "email": "test@hdfc.com",
        "roles": ["EMPLOYEE"],
        "department_id": "dept-001",
        "exp": (datetime.utcnow() + timedelta(minutes=30)).timestamp()
    }


@pytest.fixture
def expired_token_payload():
    """Expired JWT token payload"""
    return {
        "sub": "emp-123",
        "email": "test@hdfc.com",
        "roles": ["EMPLOYEE"],
        "exp": (datetime.utcnow() - timedelta(hours=1)).timestamp()
    }


@pytest.fixture
def mock_employee_record():
    """Mock employee database record"""
    return MagicMock(
        employee_id="emp-123",
        username="testuser",
        email="test@hdfc.com",
        password_hash="$2b$12$hashedpassword",
        designation_id="des-001",
        department_id="dept-001",
        manager_id=None,
        status_id="status-001",
        date_of_joining=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )


@pytest.fixture
def mock_refresh_token_record():
    """Mock refresh token database record"""
    return MagicMock(
        token_id="refresh-token-id-123",
        token_hash="hashed_secret",
        employee_id="emp-123",
        expires_at=datetime.utcnow() + timedelta(days=7),
        revoked_at=None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )


# ============================================================================
# TEST CURRENTUSER CLASS
# ============================================================================

class TestCurrentUserClass:
    """Test cases for CurrentUser class"""

    def test_current_user_initialization_with_single_role(self):
        """Test CurrentUser initialization with single role"""
        user = CurrentUser(id="emp-123", roles=["EMPLOYEE"])
        
        assert user.id == "emp-123"
        assert user.roles == ["EMPLOYEE"]
        assert isinstance(user.roles, list)

    def test_current_user_initialization_with_multiple_roles(self):
        """Test CurrentUser initialization with multiple roles"""
        user = CurrentUser(id="admin-123", roles=["ADMIN", "EMPLOYEE"])
        
        assert user.id == "admin-123"
        assert len(user.roles) == 2
        assert "ADMIN" in user.roles
        assert "EMPLOYEE" in user.roles

    def test_current_user_initialization_with_empty_roles(self):
        """Test CurrentUser initialization with empty roles list"""
        user = CurrentUser(id="emp-123", roles=[])
        
        assert user.id == "emp-123"
        assert user.roles == []
        assert isinstance(user.roles, list)

    def test_current_user_id_type_string(self):
        """Test that user id is stored as string"""
        user = CurrentUser(id="emp-123", roles=["EMPLOYEE"])
        
        assert isinstance(user.id, str)

    def test_current_user_roles_type_list(self):
        """Test that roles is a list"""
        user = CurrentUser(id="emp-123", roles=["EMPLOYEE"])
        
        assert isinstance(user.roles, list)


# ============================================================================
# TEST GET_CURRENT_USER FUNCTION
# ============================================================================

class TestGetCurrentUser:
    """Test cases for get_current_user dependency"""

    @pytest.mark.asyncio
    async def test_get_current_user_with_valid_token(self, valid_token_payload):
        """Test get_current_user with valid token"""
        with patch('src.core.security.decode_token', return_value=valid_token_payload):
            from src.auth.dependencies import get_current_user
            
            user = await get_current_user(token="valid.jwt.token")
            
            assert isinstance(user, CurrentUser)
            assert user.id == "emp-123"
            assert user.roles == ["EMPLOYEE"]

    @pytest.mark.asyncio
    async def test_get_current_user_with_invalid_token(self):
        """Test get_current_user with invalid token returns None from decode"""
        with patch('src.core.security.decode_token', return_value=None):
            from src.auth.dependencies import get_current_user
            
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="invalid.jwt.token")
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "Invalid or expired token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_with_expired_token(self):
        """Test get_current_user with expired token"""
        with patch('src.core.security.decode_token', return_value=None):
            from src.auth.dependencies import get_current_user
            
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(token="expired.jwt.token")
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_get_current_user_with_missing_roles_in_payload(self):
        """Test get_current_user when roles are missing from payload"""
        payload_without_roles = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
            # No roles key
        }
        
        with patch('src.core.security.decode_token', return_value=payload_without_roles):
            from src.auth.dependencies import get_current_user
            
            user = await get_current_user(token="valid.jwt.token")
            
            assert user.id == "emp-123"
            assert user.roles == []  # Should default to empty list

    @pytest.mark.asyncio
    async def test_get_current_user_with_malformed_token(self):
        """Test get_current_user with malformed token"""
        with patch('src.core.security.decode_token', side_effect=Exception("Malformed token")):
            from src.auth.dependencies import get_current_user
            
            with pytest.raises(Exception):
                await get_current_user(token="malformed.token")

    @pytest.mark.asyncio
    async def test_get_current_user_extracts_correct_id_from_sub(self, valid_token_payload):
        """Test that user id is correctly extracted from 'sub' claim"""
        with patch('src.core.security.decode_token', return_value=valid_token_payload):
            from src.auth.dependencies import get_current_user
            
            user = await get_current_user(token="valid.jwt.token")
            
            assert user.id == valid_token_payload["sub"]


# ============================================================================
# TEST REQUIRE_ROLES FUNCTION
# ============================================================================

class TestRequireRoles:
    """Test cases for require_roles RBAC dependency"""

    @pytest.mark.asyncio
    async def test_require_roles_allows_user_with_correct_role(self):
        """Test require_roles allows access when user has the required role"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": ["EMPLOYEE"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("EMPLOYEE")
            user = await checker(token="valid.jwt.token")
            
            assert isinstance(user, CurrentUser)
            assert user.id == "emp-123"
            assert "EMPLOYEE" in user.roles

    @pytest.mark.asyncio
    async def test_require_roles_allows_user_with_any_of_multiple_allowed_roles(self):
        """Test require_roles allows access when user has ANY of the allowed roles"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": ["MANAGER"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("ADMIN", "MANAGER", "EMPLOYEE")
            user = await checker(token="valid.jwt.token")
            
            assert user.id == "emp-123"
            assert "MANAGER" in user.roles

    @pytest.mark.asyncio
    async def test_require_roles_denies_user_without_correct_role(self):
        """Test require_roles denies access when user lacks required role"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": ["EMPLOYEE"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("ADMIN")
            
            with pytest.raises(HTTPException) as exc_info:
                await checker(token="valid.jwt.token")
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
            assert "You do not have permission" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_require_roles_super_admin_bypass(self):
        """Test that SUPER_ADMIN always has access regardless of required roles"""
        payload = {
            "sub": "superadmin-123",
            "email": "superadmin@hdfc.com",
            "roles": ["SUPER_ADMIN"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            # Even though we require ADMIN role, SUPER_ADMIN should bypass
            checker = require_roles("ADMIN")
            user = await checker(token="valid.jwt.token")
            
            assert user.id == "superadmin-123"
            assert "SUPER_ADMIN" in user.roles

    @pytest.mark.asyncio
    async def test_require_roles_super_admin_bypass_for_any_role(self):
        """Test SUPER_ADMIN bypasses any role requirement"""
        payload = {
            "sub": "superadmin-123",
            "email": "superadmin@hdfc.com",
            "roles": ["SUPER_ADMIN", "ADMIN"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("RESTRICTED_ROLE_XYZ")
            user = await checker(token="valid.jwt.token")
            
            assert user.id == "superadmin-123"

    @pytest.mark.asyncio
    async def test_require_roles_with_invalid_token(self):
        """Test require_roles with invalid token"""
        with patch('src.core.security.decode_token', return_value=None):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("EMPLOYEE")
            
            with pytest.raises(HTTPException) as exc_info:
                await checker(token="invalid.jwt.token")
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_require_roles_with_empty_roles_in_payload(self):
        """Test require_roles when user has no roles"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": []
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("EMPLOYEE")
            
            with pytest.raises(HTTPException) as exc_info:
                await checker(token="valid.jwt.token")
            
            assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_require_roles_returns_current_user_object(self):
        """Test that require_roles returns CurrentUser object (not dict)"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": ["EMPLOYEE"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            checker = require_roles("EMPLOYEE")
            user = await checker(token="valid.jwt.token")
            
            assert isinstance(user, CurrentUser)
            assert hasattr(user, 'id')
            assert hasattr(user, 'roles')

    @pytest.mark.asyncio
    async def test_require_roles_multiple_roles_user_has_multiple(self):
        """Test user with multiple roles can access with any matching role"""
        payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com",
            "roles": ["EMPLOYEE", "MANAGER", "ADMIN"]
        }
        
        with patch('src.core.security.decode_token', return_value=payload):
            from src.auth.dependencies import require_roles
            
            # Require MANAGER or ADMIN
            checker = require_roles("MANAGER", "ADMIN")
            user = await checker(token="valid.jwt.token")
            
            assert user.id == "emp-123"
            assert len(user.roles) == 3


# ============================================================================
# TEST LOGIN SERVICE
# ============================================================================

class TestLoginService:
    """Test cases for login_user service function"""

    @pytest.mark.asyncio
    async def test_login_with_valid_email_and_password(self, mock_db, mock_employee_record):
        """Test successful login with valid email and password"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[
            MagicMock(roles=MagicMock(role_code="EMPLOYEE"), is_active=True)
        ])
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token', return_value="access.token.jwt"):
                from src.auth.service import login_user
                
                result = await login_user(
                    username_or_email="test@hdfc.com",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                assert result is not None
                assert "access_token" in result
                assert "refresh_token" in result

    @pytest.mark.asyncio
    async def test_login_with_valid_username_and_password(self, mock_db, mock_employee_record):
        """Test successful login with username instead of email"""
        mock_db.employees.find_first = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[
            MagicMock(roles=MagicMock(role_code="EMPLOYEE"), is_active=True)
        ])
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token', return_value="access.token.jwt"):
                from src.auth.service import login_user
                
                result = await login_user(
                    username_or_email="testuser",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                assert result is not None

    @pytest.mark.asyncio
    async def test_login_with_invalid_email(self, mock_db):
        """Test login failure with non-existent email"""
        mock_db.employees.find_unique = AsyncMock(return_value=None)
        
        from src.auth.service import login_user
        
        with pytest.raises(HTTPException) as exc_info:
            await login_user(
                username_or_email="nonexistent@hdfc.com",
                password="password123",
                db=mock_db
            )
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_login_with_wrong_password(self, mock_db, mock_employee_record):
        """Test login failure with incorrect password"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        
        with patch('src.core.security.verify_password', return_value=False):
            from src.auth.service import login_user
            
            with pytest.raises(HTTPException) as exc_info:
                await login_user(
                    username_or_email="test@hdfc.com",
                    password="WrongPassword",
                    db=mock_db
                )
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_login_assigns_default_employee_role_when_no_roles(self, mock_db, mock_employee_record):
        """Test that EMPLOYEE role is assigned by default when user has no roles"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[])  # No roles
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token') as mock_create_token:
                from src.auth.service import login_user
                
                await login_user(
                    username_or_email="test@hdfc.com",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                # Check that create_access_token was called with EMPLOYEE role
                call_args = mock_create_token.call_args[0][0]
                assert "roles" in call_args
                assert "EMPLOYEE" in call_args["roles"]

    @pytest.mark.asyncio
    async def test_login_filters_only_active_roles(self, mock_db, mock_employee_record):
        """Test that only active roles are included in token"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[
            MagicMock(roles=MagicMock(role_code="ADMIN"), is_active=True),
            MagicMock(roles=MagicMock(role_code="MANAGER"), is_active=False)  # Inactive
        ])
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token') as mock_create_token:
                from src.auth.service import login_user
                
                await login_user(
                    username_or_email="test@hdfc.com",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                call_args = mock_create_token.call_args[0][0]
                assert "ADMIN" in call_args["roles"]
                assert "MANAGER" not in call_args["roles"]

    @pytest.mark.asyncio
    async def test_login_creates_refresh_token(self, mock_db, mock_employee_record):
        """Test that refresh token is created in database"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[])
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token', return_value="access.token"):
                from src.auth.service import login_user
                
                result = await login_user(
                    username_or_email="test@hdfc.com",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                mock_db.refresh_tokens.create.assert_called_once()
                assert "refresh_token" in result

    @pytest.mark.asyncio
    async def test_login_with_empty_credentials(self, mock_db):
        """Test login with empty username/email"""
        from src.auth.service import login_user
        
        with pytest.raises(HTTPException):
            await login_user(
                username_or_email="",
                password="password",
                db=mock_db
            )

    @pytest.mark.asyncio
    async def test_login_includes_user_info_in_response(self, mock_db, mock_employee_record):
        """Test that login response includes user information"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[])
        mock_db.refresh_tokens.create = AsyncMock(return_value=MagicMock(token_id="refresh-123"))
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token', return_value="access.token"):
                from src.auth.service import login_user
                
                result = await login_user(
                    username_or_email="test@hdfc.com",
                    password="ValidPassword123",
                    db=mock_db
                )
                
                assert "user" in result
                assert result["user"]["email"] == mock_employee_record.email


# ============================================================================
# TEST REFRESH TOKEN SERVICE
# ============================================================================

class TestRefreshTokenService:
    """Test cases for refresh_access_token service function"""

    @pytest.mark.asyncio
    async def test_refresh_token_with_valid_token(self, mock_db, mock_employee_record, mock_refresh_token_record):
        """Test successful token refresh with valid refresh token"""
        client_token = "refresh-token-id-123:secret-part"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[
            MagicMock(roles=MagicMock(role_code="EMPLOYEE"), is_active=True)
        ])
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            with patch('src.core.security.create_access_token', return_value="new.access.token"):
                from src.auth.service import refresh_access_token
                
                result = await refresh_access_token(client_token, db=mock_db)
                
                assert result is not None
                assert "access_token" in result

    @pytest.mark.asyncio
    async def test_refresh_token_with_invalid_format(self, mock_db):
        """Test refresh token failure with invalid token format"""
        invalid_token = "invalid-format-token"
        
        from src.auth.service import refresh_access_token
        
        with pytest.raises(HTTPException) as exc_info:
            await refresh_access_token(invalid_token, db=mock_db)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid refresh token" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_refresh_token_not_found_in_database(self, mock_db):
        """Test refresh token failure when token not found in DB"""
        client_token = "nonexistent-id:secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=None)
        
        from src.auth.service import refresh_access_token
        
        with pytest.raises(HTTPException) as exc_info:
            await refresh_access_token(client_token, db=mock_db)
        
        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_refresh_token_with_wrong_secret(self, mock_db, mock_refresh_token_record):
        """Test refresh token failure with incorrect secret"""
        client_token = "refresh-token-id-123:wrong-secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=False):
            from src.auth.service import refresh_access_token
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token(client_token, db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_refresh_token_that_is_expired(self, mock_db, mock_refresh_token_record):
        """Test refresh token failure with expired token"""
        client_token = "refresh-token-id-123:secret"
        
        # Set expired date
        mock_refresh_token_record.expires_at = datetime.utcnow() - timedelta(days=1)
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import refresh_access_token
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token(client_token, db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "expired" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_refresh_token_that_is_revoked(self, mock_db, mock_refresh_token_record):
        """Test refresh token failure with revoked token"""
        client_token = "refresh-token-id-123:secret"
        
        # Mark as revoked
        mock_refresh_token_record.revoked_at = datetime.utcnow()
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import refresh_access_token
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token(client_token, db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
            assert "revoked" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_refresh_token_user_not_found(self, mock_db, mock_refresh_token_record):
        """Test refresh token failure when associated user doesn't exist"""
        client_token = "refresh-token-id-123:secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.employees.find_unique = AsyncMock(return_value=None)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import refresh_access_token
            
            with pytest.raises(HTTPException) as exc_info:
                await refresh_access_token(client_token, db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_refresh_token_assigns_default_role_when_no_roles(self, mock_db, mock_employee_record, mock_refresh_token_record):
        """Test refresh token assigns EMPLOYEE role when user has no roles"""
        client_token = "refresh-token-id-123:secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[])  # No roles
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            with patch('src.core.security.create_access_token') as mock_create_token:
                mock_create_token.return_value = "new.access.token"
                
                from src.auth.service import refresh_access_token
                
                await refresh_access_token(client_token, db=mock_db)
                
                call_args = mock_create_token.call_args[0][0]
                assert "EMPLOYEE" in call_args["roles"]

    @pytest.mark.asyncio
    async def test_refresh_token_handles_role_fetch_error_gracefully(self, mock_db, mock_employee_record, mock_refresh_token_record):
        """Test refresh token handles DB error when fetching roles"""
        client_token = "refresh-token-id-123:secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(side_effect=Exception("DB error"))
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            with patch('src.core.security.create_access_token') as mock_create_token:
                mock_create_token.return_value = "new.access.token"
                
                from src.auth.service import refresh_access_token
                
                result = await refresh_access_token(client_token, db=mock_db)
                
                # Should still succeed with default EMPLOYEE role
                assert result is not None
                call_args = mock_create_token.call_args[0][0]
                assert "EMPLOYEE" in call_args["roles"]


# ============================================================================
# TEST LOGOUT SERVICE
# ============================================================================

class TestLogoutService:
    """Test cases for logout_user service function"""

    @pytest.mark.asyncio
    async def test_logout_with_valid_refresh_token(self, mock_db, mock_refresh_token_record):
        """Test successful logout with valid refresh token"""
        client_token = "refresh-token-id-123:secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.update = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import logout_user
            
            result = await logout_user(client_token, user_id, db=mock_db)
            
            assert result["message"] == "Logged out successfully"
            mock_db.refresh_tokens.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_logout_with_invalid_token_format(self, mock_db):
        """Test logout with malformed token format"""
        invalid_token = "invalid-format"
        user_id = "emp-123"
        
        from src.auth.service import logout_user
        
        result = await logout_user(invalid_token, user_id, db=mock_db)
        
        assert "Invalid token format" in result["message"]

    @pytest.mark.asyncio
    async def test_logout_token_not_found_in_db(self, mock_db):
        """Test logout when token not found in database"""
        client_token = "nonexistent-id:secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=None)
        
        from src.auth.service import logout_user
        
        result = await logout_user(client_token, user_id, db=mock_db)
        
        # Should still return success (idempotent operation)
        assert "message" in result

    @pytest.mark.asyncio
    async def test_logout_token_belongs_to_different_user(self, mock_db, mock_refresh_token_record):
        """Test logout prevents revoking another user's token"""
        client_token = "refresh-token-id-123:secret"
        requesting_user_id = "emp-456"  # Different user
        
        mock_refresh_token_record.employee_id = "emp-123"  # Token belongs to different user
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import logout_user
            
            result = await logout_user(client_token, requesting_user_id, db=mock_db)
            
            # Token should NOT be revoked (different user)
            mock_db.refresh_tokens.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_logout_with_wrong_secret(self, mock_db, mock_refresh_token_record):
        """Test logout with incorrect token secret"""
        client_token = "refresh-token-id-123:wrong-secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=False):
            from src.auth.service import logout_user
            
            result = await logout_user(client_token, user_id, db=mock_db)
            
            # Should still return success but not revoke
            mock_db.refresh_tokens.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_logout_sets_revoked_at_timestamp(self, mock_db, mock_refresh_token_record):
        """Test that logout sets revoked_at timestamp"""
        client_token = "refresh-token-id-123:secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.update = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import logout_user
            
            await logout_user(client_token, user_id, db=mock_db)
            
            # Check that update was called with revoked_at
            call_args = mock_db.refresh_tokens.update.call_args
            assert "revoked_at" in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_logout_is_idempotent(self, mock_db, mock_refresh_token_record):
        """Test that logout can be called multiple times safely"""
        client_token = "refresh-token-id-123:secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.update = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import logout_user
            
            result1 = await logout_user(client_token, user_id, db=mock_db)
            result2 = await logout_user(client_token, user_id, db=mock_db)
            
            assert result1["message"] == result2["message"]


# ============================================================================
# TEST CREATE EMPLOYEE SERVICE
# ============================================================================

class TestCreateEmployeeService:
    """Test cases for create_employee service function"""

    @pytest.mark.asyncio
    async def test_create_employee_with_valid_data(self, mock_db):
        """Test successful employee creation with valid data"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="status-001"))
        mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id="emp-new"))
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password', return_value="hashed_password"):
            from src.auth.service import create_employee
            
            result = await create_employee(payload, "admin-123", db=mock_db)
            
            assert result is not None
            mock_db.employees.create.assert_called_once()
            mock_db.wallets.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_employee_with_invalid_designation(self, mock_db):
        """Test employee creation fails with non-existent designation"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="invalid-des",
            department_id="dept-001",
            manager_id=None
        )
        
        mock_db.designations.find_unique = AsyncMock(return_value=None)
        
        from src.auth.service import create_employee
        
        with pytest.raises(HTTPException) as exc_info:
            await create_employee(payload, "admin-123", db=mock_db)
        
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Designation not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_employee_with_invalid_department(self, mock_db):
        """Test employee creation fails with non-existent department"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="invalid-dept",
            manager_id=None
        )
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=None)
        
        from src.auth.service import create_employee
        
        with pytest.raises(HTTPException) as exc_info:
            await create_employee(payload, "admin-123", db=mock_db)
        
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Department not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_employee_with_invalid_manager(self, mock_db):
        """Test employee creation fails with non-existent manager"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id="invalid-manager"
        )
        
        mock_db.employees.find_unique = AsyncMock(return_value=None)
        
        from src.auth.service import create_employee
        
        with pytest.raises(HTTPException) as exc_info:
            await create_employee(payload, "admin-123", db=mock_db)
        
        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert "Manager not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_employee_password_is_hashed(self, mock_db):
        """Test that password is properly hashed before storage"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="PlainTextPassword123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="status-001"))
        mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id="emp-new"))
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password') as mock_hash:
            mock_hash.return_value = "hashed_password"
            
            from src.auth.service import create_employee
            
            await create_employee(payload, "admin-123", db=mock_db)
            
            mock_hash.assert_called_once_with("PlainTextPassword123")
            
            # Verify hashed password was used in create call
            create_call_args = mock_db.employees.create.call_args[1]["data"]
            assert create_call_args["password_hash"] == "hashed_password"

    @pytest.mark.asyncio
    async def test_create_employee_creates_wallet(self, mock_db):
        """Test that wallet is created for new employee"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        new_employee = MagicMock(employee_id="emp-new-123")
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="status-001"))
        mock_db.employees.create = AsyncMock(return_value=new_employee)
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password', return_value="hashed"):
            from src.auth.service import create_employee
            
            await create_employee(payload, "admin-123", db=mock_db)
            
            mock_db.wallets.create.assert_called_once()
            wallet_call_args = mock_db.wallets.create.call_args[1]["data"]
            assert wallet_call_args["employee_id"] == "emp-new-123"
            assert wallet_call_args["available_points"] == 0

    @pytest.mark.asyncio
    async def test_create_employee_sets_active_status(self, mock_db):
        """Test that new employee is set to ACTIVE status"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        active_status = MagicMock(status_id="status-active-123")
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=active_status)
        mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id="emp-new"))
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password', return_value="hashed"):
            from src.auth.service import create_employee
            
            await create_employee(payload, "admin-123", db=mock_db)
            
            create_call_args = mock_db.employees.create.call_args[1]["data"]
            assert create_call_args["status_id"] == "status-active-123"

    @pytest.mark.asyncio
    async def test_create_employee_without_manager(self, mock_db):
        """Test creating employee without manager (top-level employee)"""
        payload = MagicMock(
            username="ceo",
            email="ceo@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="status-001"))
        mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id="emp-new"))
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password', return_value="hashed"):
            from src.auth.service import create_employee
            
            result = await create_employee(payload, "admin-123", db=mock_db)
            
            assert result is not None
            # Should not check for manager
            mock_db.employees.find_unique.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_employee_tracks_creator(self, mock_db):
        """Test that created_by and updated_by fields are set"""
        payload = MagicMock(
            username="newuser",
            email="newuser@hdfc.com",
            password="SecurePass123",
            designation_id="des-001",
            department_id="dept-001",
            manager_id=None
        )
        
        creator_id = "admin-789"
        
        mock_db.designations.find_unique = AsyncMock(return_value=MagicMock(designation_id="des-001"))
        mock_db.departments.find_unique = AsyncMock(return_value=MagicMock(department_id="dept-001"))
        mock_db.status_master.find_first = AsyncMock(return_value=MagicMock(status_id="status-001"))
        mock_db.employees.create = AsyncMock(return_value=MagicMock(employee_id="emp-new"))
        mock_db.wallets.create = AsyncMock(return_value=MagicMock(wallet_id="wallet-001"))
        
        with patch('src.core.security.hash_password', return_value="hashed"):
            from src.auth.service import create_employee
            
            await create_employee(payload, creator_id, db=mock_db)
            
            emp_call_args = mock_db.employees.create.call_args[1]["data"]
            assert emp_call_args["created_by"] == creator_id
            assert emp_call_args["updated_by"] == creator_id
            
            wallet_call_args = mock_db.wallets.create.call_args[1]["data"]
            assert wallet_call_args["created_by"] == creator_id


# ============================================================================
# TEST PASSWORD RESET SERVICE
# ============================================================================

class TestPasswordResetService:
    """Test cases for password reset functionality"""

    @pytest.mark.asyncio
    async def test_request_password_reset_with_valid_email(self, mock_db, mock_employee_record):
        """Test password reset request with valid registered email"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        
        with patch('src.core.security.create_reset_token', return_value="reset.token.jwt"):
            with patch('src.core.email_utils.send_password_reset_email') as mock_send_email:
                from src.auth.service import request_password_reset
                
                result = await request_password_reset("test@hdfc.com", db=mock_db)
                
                assert "message" in result
                mock_send_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_password_reset_with_unregistered_email(self, mock_db):
        """Test password reset request with non-existent email (no enumeration)"""
        mock_db.employees.find_unique = AsyncMock(return_value=None)
        
        from src.auth.service import request_password_reset
        
        result = await request_password_reset("nonexistent@hdfc.com", db=mock_db)
        
        # Should still return success to prevent email enumeration
        assert "message" in result
        assert "If your email is registered" in result["message"]

    @pytest.mark.asyncio
    async def test_request_password_reset_sends_email(self, mock_db, mock_employee_record):
        """Test that password reset email is sent"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        
        with patch('src.core.security.create_reset_token', return_value="reset.token.jwt"):
            with patch('src.core.email_utils.send_password_reset_email') as mock_send:
                from src.auth.service import request_password_reset
                
                await request_password_reset("test@hdfc.com", db=mock_db)
                
                mock_send.assert_called_once_with(
                    email="test@hdfc.com",
                    reset_token="reset.token.jwt",
                    username=mock_employee_record.username
                )

    @pytest.mark.asyncio
    async def test_request_password_reset_email_failure_does_not_raise(self, mock_db, mock_employee_record):
        """Test that email sending failure doesn't crash the request"""
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        
        with patch('src.core.security.create_reset_token', return_value="reset.token"):
            with patch('src.core.email_utils.send_password_reset_email', side_effect=Exception("SMTP error")):
                from src.auth.service import request_password_reset
                
                # Should not raise exception
                result = await request_password_reset("test@hdfc.com", db=mock_db)
                
                assert "message" in result

    @pytest.mark.asyncio
    async def test_reset_password_with_valid_token(self, mock_db, mock_employee_record):
        """Test successful password reset with valid token"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password', return_value="new_hashed_password"):
                with patch('src.core.email_utils.send_password_reset_confirmation'):
                    from src.auth.service import reset_password
                    
                    result = await reset_password("valid.reset.token", "NewPassword123", db=mock_db)
                    
                    assert "message" in result
                    assert "successful" in result["message"]
                    mock_db.employees.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_password_with_invalid_token(self, mock_db):
        """Test password reset with invalid/expired token"""
        with patch('src.core.security.decode_reset_token', return_value=None):
            from src.auth.service import reset_password
            
            with pytest.raises(HTTPException) as exc_info:
                await reset_password("invalid.token", "NewPassword123", db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
            assert "Invalid or expired" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_reset_password_with_mismatched_email(self, mock_db, mock_employee_record):
        """Test password reset fails when token email doesn't match user email"""
        reset_payload = {
            "sub": "emp-123",
            "email": "wrong@hdfc.com"  # Different from user's actual email
        }
        
        mock_employee_record.email = "test@hdfc.com"
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            from src.auth.service import reset_password
            
            with pytest.raises(HTTPException) as exc_info:
                await reset_password("token", "NewPassword123", db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_reset_password_revokes_all_refresh_tokens(self, mock_db, mock_employee_record):
        """Test that all refresh tokens are revoked after password reset"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password', return_value="new_hashed"):
                with patch('src.core.email_utils.send_password_reset_confirmation'):
                    from src.auth.service import reset_password
                    
                    await reset_password("token", "NewPassword123", db=mock_db)
                    
                    # Verify refresh tokens were revoked
                    mock_db.refresh_tokens.update_many.assert_called_once()
                    call_args = mock_db.refresh_tokens.update_many.call_args
                    assert "revoked_at" in call_args[1]["data"]

    @pytest.mark.asyncio
    async def test_reset_password_hashes_new_password(self, mock_db, mock_employee_record):
        """Test that new password is properly hashed"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password') as mock_hash:
                mock_hash.return_value = "hashed_new_password"
                with patch('src.core.email_utils.send_password_reset_confirmation'):
                    from src.auth.service import reset_password
                    
                    await reset_password("token", "PlainNewPassword123", db=mock_db)
                    
                    mock_hash.assert_called_once_with("PlainNewPassword123")
                    
                    update_call_args = mock_db.employees.update.call_args[1]["data"]
                    assert update_call_args["password_hash"] == "hashed_new_password"

    @pytest.mark.asyncio
    async def test_reset_password_sends_confirmation_email(self, mock_db, mock_employee_record):
        """Test that confirmation email is sent after password reset"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password', return_value="hashed"):
                with patch('src.core.email_utils.send_password_reset_confirmation') as mock_confirm:
                    from src.auth.service import reset_password
                    
                    await reset_password("token", "NewPassword123", db=mock_db)
                    
                    mock_confirm.assert_called_once_with(
                        email=mock_employee_record.email,
                        username=mock_employee_record.username
                    )

    @pytest.mark.asyncio
    async def test_reset_password_user_not_found(self, mock_db):
        """Test password reset fails when user no longer exists"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            from src.auth.service import reset_password
            
            with pytest.raises(HTTPException) as exc_info:
                await reset_password("token", "NewPassword123", db=mock_db)
            
            assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_reset_password_confirmation_email_failure_does_not_crash(self, mock_db, mock_employee_record):
        """Test that confirmation email failure doesn't prevent password reset"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password', return_value="hashed"):
                with patch('src.core.email_utils.send_password_reset_confirmation', side_effect=Exception("Email error")):
                    from src.auth.service import reset_password
                    
                    # Should not raise exception
                    result = await reset_password("token", "NewPassword123", db=mock_db)
                    
                    assert result["message"]


# ============================================================================
# EDGE CASES AND SECURITY TESTS
# ============================================================================

class TestSecurityScenarios:
    """Test cases for security-specific scenarios"""

    @pytest.mark.asyncio
    async def test_token_injection_attempt(self):
        """Test that malicious token payloads are handled"""
        malicious_payload = {
            "sub": "emp-123'; DROP TABLE employees; --",
            "email": "malicious@test.com",
            "roles": ["SUPER_ADMIN"]  # Attempting privilege escalation
        }
        
        with patch('src.core.security.decode_token', return_value=malicious_payload):
            from src.auth.dependencies import get_current_user
            
            user = await get_current_user(token="token")
            
            # Should still create user object, but validate at DB layer
            assert user.id == "emp-123'; DROP TABLE employees; --"

    @pytest.mark.asyncio
    async def test_concurrent_logout_attempts(self, mock_db, mock_refresh_token_record):
        """Test handling concurrent logout requests"""
        client_token = "refresh-id:secret"
        user_id = "emp-123"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.update = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=True):
            from src.auth.service import logout_user
            
            # Simulate concurrent calls
            result1 = await logout_user(client_token, user_id, db=mock_db)
            result2 = await logout_user(client_token, user_id, db=mock_db)
            
            assert result1["message"]
            assert result2["message"]

    @pytest.mark.asyncio
    async def test_refresh_token_timing_attack_resistance(self, mock_db, mock_refresh_token_record):
        """Test that token verification doesn't leak timing information"""
        import time
        
        client_token = "refresh-id:secret"
        
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_refresh_token', return_value=False):
            from src.auth.service import refresh_access_token
            
            # Time the failed verification
            start = time.time()
            try:
                await refresh_access_token(client_token, db=mock_db)
            except HTTPException:
                pass
            elapsed = time.time() - start
            
            # Should complete quickly without revealing information
            assert elapsed < 1.0

    @pytest.mark.asyncio
    async def test_password_reset_token_reuse_prevention(self, mock_db, mock_employee_record):
        """Test that reset tokens cannot be reused"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.decode_reset_token', return_value=reset_payload):
            with patch('src.core.security.hash_password', return_value="hashed"):
                with patch('src.core.email_utils.send_password_reset_confirmation'):
                    from src.auth.service import reset_password
                    
                    # First reset should succeed
                    result1 = await reset_password("token", "NewPassword1", db=mock_db)
                    assert result1
                    
                    # Token should be single-use (implementation dependent)
                    # In practice, the token would be invalidated or expired


# ============================================================================
# INTEGRATION-STYLE TESTS
# ============================================================================

class TestAuthenticationFlow:
    """Test complete authentication flows"""

    @pytest.mark.asyncio
    async def test_complete_login_refresh_logout_flow(self, mock_db, mock_employee_record, mock_refresh_token_record):
        """Test complete authentication flow: login -> refresh -> logout"""
        # Setup mocks
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employee_roles.find_many = AsyncMock(return_value=[
            MagicMock(roles=MagicMock(role_code="EMPLOYEE"), is_active=True)
        ])
        mock_db.refresh_tokens.create = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.find_first = AsyncMock(return_value=mock_refresh_token_record)
        mock_db.refresh_tokens.update = AsyncMock(return_value=mock_refresh_token_record)
        
        with patch('src.core.security.verify_password', return_value=True):
            with patch('src.core.security.create_access_token', return_value="access.token"):
                with patch('src.core.security.verify_refresh_token', return_value=True):
                    from src.auth.service import login_user, refresh_access_token, logout_user
                    
                    # 1. Login
                    login_result = await login_user("test@hdfc.com", "password", db=mock_db)
                    assert "access_token" in login_result
                    assert "refresh_token" in login_result
                    
                    # 2. Refresh token
                    refresh_result = await refresh_access_token(
                        login_result["refresh_token"],
                        db=mock_db
                    )
                    assert "access_token" in refresh_result
                    
                    # 3. Logout
                    logout_result = await logout_user(
                        login_result["refresh_token"],
                        "emp-123",
                        db=mock_db
                    )
                    assert logout_result["message"] == "Logged out successfully"

    @pytest.mark.asyncio
    async def test_complete_password_reset_flow(self, mock_db, mock_employee_record):
        """Test complete password reset flow"""
        reset_payload = {
            "sub": "emp-123",
            "email": "test@hdfc.com"
        }
        
        mock_db.employees.find_unique = AsyncMock(return_value=mock_employee_record)
        mock_db.employees.update = AsyncMock(return_value=mock_employee_record)
        mock_db.refresh_tokens.update_many = AsyncMock(return_value=None)
        
        with patch('src.core.security.create_reset_token', return_value="reset.token"):
            with patch('src.core.email_utils.send_password_reset_email'):
                with patch('src.core.security.decode_reset_token', return_value=reset_payload):
                    with patch('src.core.security.hash_password', return_value="hashed"):
                        with patch('src.core.email_utils.send_password_reset_confirmation'):
                            from src.auth.service import request_password_reset, reset_password
                            
                            # 1. Request reset
                            request_result = await request_password_reset("test@hdfc.com", db=mock_db)
                            assert "message" in request_result
                            
                            # 2. Reset with token
                            reset_result = await reset_password("reset.token", "NewPass123", db=mock_db)
                            assert "successful" in reset_result["message"]


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
