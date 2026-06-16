import pytest
import jwt
import httpx
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException, Request, status
from src.common.dependencies import (
    get_current_user, 
    check_route_permission, 
    _is_public, 
    _build_route_key,
    CurrentUser,
    get_auth_client,
    close_auth_client
)

DEP = "src.common.dependencies"

@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    # Default state for a fresh request mock
    request.scope = {"path": "/aabhar/v1/analytics/dashboard", "route": MagicMock()}
    request.scope["route"].path = "/dashboard"
    request.url.path = "/aabhar/v1/analytics/dashboard"
    request.method = "GET"
    request.app.root_path = "/aabhar/v1/analytics"
    request.state = MagicMock()
    return request

class TestDependencies:

    # ===========================================================================
    # 1. UTILITY TESTS (Sync - removed asyncio mark)
    # ===========================================================================
    def test_is_public(self, mock_request):
        mock_request.scope["path"] = "/health"
        assert _is_public(mock_request) is True
        
        mock_request.scope["path"] = "/private/data"
        assert _is_public(mock_request) is False

    def test_build_route_key(self):
        # 1. Manually create a mock that behaves like a FastAPI Request
        mock_req = MagicMock(spec=Request)
        mock_req.method = "POST"
        
        # 2. FastAPI components must return strings for concatenation to work
        mock_req.app = MagicMock()
        mock_req.app.root_path = "/aabhar/v1/auth"
        
        # 3. Simulate a matched APIRoute object
        from fastapi.routing import APIRoute
        mock_route = MagicMock(spec=APIRoute)
        mock_route.path = "/login"
        
        # 4. Inject into scope
        mock_req.scope = {"route": mock_route}

        # 5. Execute
        key = _build_route_key(mock_req)
        
        # 6. Assert exact string match
        assert key == "POST:/aabhar/v1/auth/login"

    @pytest.mark.asyncio
    async def test_auth_client_singleton(self):
        client = get_auth_client()
        assert isinstance(client, httpx.AsyncClient)
        await close_auth_client()

    # ===========================================================================
    # 2. GET CURRENT USER (AUTHENTICATION)
    # ===========================================================================
    @pytest.mark.asyncio
    async def test_get_current_user_public_path(self, mock_request):
        mock_request.scope["path"] = "/health"
        user = await get_current_user(mock_request, None)
        assert user.id == "system"
        assert "PUBLIC" in user.roles

    @pytest.mark.asyncio
    async def test_get_current_user_no_credentials(self, mock_request):
        with pytest.raises(HTTPException) as exc:
            await get_current_user(mock_request, None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    @patch(f"{DEP}.cache_get", AsyncMock(return_value=None))
    @patch(f"{DEP}.get_auth_client")
    async def test_get_current_user_auth_service_success(self, mock_get_client, mock_request):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "valid": True, 
            "user_id": "u1", 
            "email": "a@b.com", 
            "roles": ["employee"]
        }
        mock_client.post.return_value = mock_response
        mock_get_client.return_value = mock_client
        
        creds = MagicMock(credentials="valid_token")
        user = await get_current_user(mock_request, creds)
        
        assert user.id == "u1"
        assert "EMPLOYEE" in user.roles

    @pytest.mark.asyncio
    @patch(f"{DEP}.cache_get", AsyncMock(return_value=None))
    @patch(f"{DEP}.get_auth_client")
    @patch(f"{DEP}.jwt.decode")
    async def test_get_current_user_fallback_local_jwt(self, mock_jwt, mock_get_client, mock_request):
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.RequestError("Auth Service Down")
        mock_get_client.return_value = mock_client
        
        mock_jwt.return_value = {
            "sub": "local_u1", 
            "email": "local@test.com", 
            "roles": ["manager"]
        }
        
        creds = MagicMock(credentials="token")
        user = await get_current_user(mock_request, creds)
        assert user.id == "local_u1"

    # ===========================================================================
    # 3. CHECK ROUTE PERMISSIONS (AUTHORIZATION)
    # ===========================================================================
    @pytest.mark.asyncio
    async def test_check_permission_super_admin_bypass(self, mock_request):
        user = CurrentUser(id="admin", email="a@b.com", roles=["SUPER_ADMIN"])
        result = await check_route_permission(mock_request, user)
        assert result == user

    @pytest.mark.asyncio
    @patch(f"{DEP}.cache_get", AsyncMock(return_value=None))
    @patch(f"{DEP}.db.route_permissions.find_many", new_callable=AsyncMock) # Fixed: Force AsyncMock
    async def test_check_permission_forbidden(self, mock_find, mock_request):
        user = CurrentUser(id="u1", email="u@b.com", roles=["EMPLOYEE"])
        
        mock_perm = MagicMock()
        mock_perm.roles.role_code = "MANAGER"
        mock_find.return_value = [mock_perm]
        
        with pytest.raises(HTTPException) as exc:
            await check_route_permission(mock_request, user)
        
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @patch(f"{DEP}.cache_get", AsyncMock(return_value=["EMPLOYEE"]))
    async def test_check_permission_cache_hit(self, mock_request):
        user = CurrentUser(id="u1", email="u@b.com", roles=["EMPLOYEE"])
        result = await check_route_permission(mock_request, user)
        assert result == user