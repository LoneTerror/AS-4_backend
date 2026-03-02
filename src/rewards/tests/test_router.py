import pytest
from unittest.mock import AsyncMock

def test_get_categories_route(app_client, mocker):
    # Mock the RewardService instance method rather than the module level function
    mock_get_categories = mocker.patch(
        "src.rewards.service.RewardService.get_categories",
        new_callable=AsyncMock
    )
    
    # Dummy returned data matching the schema
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

    response = app_client.get("/v1/rewards/categories?active_only=true")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["category_code"] == "CAT-TECH"
    
    # Verify it passed the query param down to the service
    mock_get_categories.assert_called_once_with(active_only=True)