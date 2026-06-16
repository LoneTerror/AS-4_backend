import pytest
from unittest.mock import AsyncMock
from src.main import app # Import your FastAPI app instance
from src.common.dependencies import check_route_permission, CurrentUser
from src.rewards.service import RewardService

def test_get_categories_route(app_client, mocker):
    # 1. SETUP: Mock a logged-in user to bypass the 401 Unauthorized error
    mock_user = CurrentUser(
        id="test-user-id", 
        roles=["EMPLOYEE"], 
        email="test@example.com", 
        org_id="test-org-id"
    )
    
    # Override the security dependency globally for this test session
    app.dependency_overrides[check_route_permission] = lambda: mock_user

    # 2. PATCH: Mock the RewardService method
    mock_get_categories = mocker.patch.object(
        RewardService, 
        "get_categories", 
        new_callable=AsyncMock
    )
    
    mock_get_categories.return_value = [
        {
            "category_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
            "category_name": "Tech",
            "category_code": "CAT-TECH",
            "description": "Gadgets",
            "is_active": True,
            "created_at": "2026-03-02T12:00:00Z"
        }
    ]

    # 3. EXECUTE: Call the endpoint
    try:
        response = app_client.get("/aabhar/v1/rewards/categories?is_active=true")
        
        # 4. ASSERT
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["category_code"] == "CAT-TECH"
        
        # Verify the router passed the correct logic to the service
        mock_get_categories.assert_called_once_with(is_active=True)
    
    finally:
        # 5. CLEANUP: Always clear overrides so other tests aren't affected
        app.dependency_overrides.clear()