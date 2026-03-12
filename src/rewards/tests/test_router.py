import pytest
from unittest.mock import AsyncMock
# Import the actual service class from the rewards package
from src.rewards.service import RewardService

def test_get_categories_route(app_client, mocker):
    # Patch the class method directly using the imported class reference
    mock_get_categories = mocker.patch.object(
        RewardService, 
        "get_categories", 
        new_callable=AsyncMock
    )
    
    # Dummy data matching your schema
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

    response = app_client.get("/v1/rewards/categories?is_active=true")
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["category_code"] == "CAT-TECH"
    
    # Verify the router passed the correct logic to the service
    mock_get_categories.assert_called_once_with(is_active=True)