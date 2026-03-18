import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.analytics.main import app
from src.common.dependencies import check_route_permission

# ===========================================================================
# 1. AUTHENTICATION OVERRIDE
# ===========================================================================
class MockUser:
    def __init__(self):
        self.id = "emp-123"
        self.role = "SUPER_ADMIN"

async def override_auth():
    return MockUser()

app.dependency_overrides[check_route_permission] = override_auth

client = TestClient(app)
ROUTER = "src.analytics.router"

# ===========================================================================
# 2. ROUTER TESTS
# ===========================================================================

class TestAnalyticsRouter:

    def test_recent_reviews(self):
        with patch(f"{ROUTER}.get_recent_reviews_list", AsyncMock(return_value=[])) as mock_svc:
            response = client.get("/dashboard/recent-reviews")
            assert response.status_code == 200
            mock_svc.assert_called_once_with("emp-123")

    def test_leaderboard(self):
        with patch(f"{ROUTER}.get_leaderboard_list", AsyncMock(return_value=[])):
            response = client.get("/dashboard/leaderboard")
            assert response.status_code == 200

    def test_platform_stats(self):
        mock_metric = {"value": 0, "this_month": 0, "last_month": 0, "trend": 0.0, "is_positive": True}
        mock_stats = {
            "total_points": mock_metric,
            "rewards_redeemed": mock_metric,
            "reviews_received": mock_metric,
            "active_users": mock_metric
        }
        with patch(f"{ROUTER}.get_platform_stats", AsyncMock(return_value=mock_stats)):
            response = client.get("/dashboard/platform-stats")
            assert response.status_code == 200

    def test_list_teams(self):
        with patch(f"{ROUTER}.get_teams_summary", AsyncMock(return_value=[])):
            response = client.get("/dashboard/teams")
            assert response.status_code == 200

    def test_team_detail_found(self):
        valid_uuid = "12345678-1234-5678-1234-567812345678"
        mock_report = {
            "department_id": valid_uuid,
            "department_name": "IT",
            # Moved these to the root level!
            "total_members": 5, 
            "total_points": 500, 
            "total_reviews": 10,           
            "total_rewards": 2,            
            "avg_performance_score": 90.5,
            "members": []
        }
        with patch(f"{ROUTER}.get_team_report", AsyncMock(return_value=mock_report)):
            response = client.get(f"/dashboard/teams/{valid_uuid}")
            assert response.status_code == 200
            assert response.json()["department_name"] == "IT"

    def test_team_detail_not_found(self):
        with patch(f"{ROUTER}.get_team_report", AsyncMock(return_value=None)):
            response = client.get("/dashboard/teams/unknown-dept")
            assert response.status_code == 404
            # Safely check the raw text since the custom middleware alters the JSON structure
            assert "unknown-dept" in response.text

    def test_participation_overview(self):
        mock_overview = {
            "stats": {
                "total_employees": 100, 
                "active_participants": 50,
                "non_participants": 50,          # Added 
                "participation_rate": 50.0,
                "total_points_awarded": 1000,
                "total_reviews_given": 50,
                "avg_reviews_per_employee": 0.5, # Added
                "avg_reviews_last_month": 0.4    # Added
            },
            "pie": [],                           # Added
            "by_department": []
        }
        with patch(f"{ROUTER}.get_participation_overview", AsyncMock(return_value=mock_overview)):
            response = client.get("/dashboard/participation")
            assert response.status_code == 200

    def test_recognition_trend(self):
        mock_trend = {"range": "6m", "data": []}
        with patch(f"{ROUTER}.get_recognition_trend", AsyncMock(return_value=mock_trend)):
            response = client.get("/dashboard/recognition-trend?range=3m")
            assert response.status_code == 200

    def test_recognition_users(self):
        # Added the 'pages' field required by PaginatedUserRecognition
        mock_paginated = {"total": 0, "page": 1, "limit": 20, "pages": 1, "items": []}
        with patch(f"{ROUTER}.get_recognition_users", AsyncMock(return_value=mock_paginated)):
            response = client.get("/dashboard/recognition/users?range=week&page=2&limit=50")
            assert response.status_code == 200

    def test_recognition_teams(self):
        # Added the 'pages' field required by PaginatedTeamRecognition
        mock_paginated = {"total": 0, "page": 1, "limit": 10, "pages": 1, "items": []}
        with patch(f"{ROUTER}.get_recognition_teams", AsyncMock(return_value=mock_paginated)):
            response = client.get("/dashboard/recognition/teams?range=year&page=1&limit=10")
            assert response.status_code == 200