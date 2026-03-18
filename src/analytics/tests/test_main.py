import os
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

# 1. CRITICAL: We must set this environment variable BEFORE importing main.py.
# Otherwise, os.getenv() returns None, and .split(",") will crash the import.
os.environ["FRONTEND_CORS_ORIGINS"] = "http://localhost:3000,http://localhost:3001"

from src.analytics.main import app

# Create a single TestClient instance for simple route testing
client = TestClient(app)

MAIN = "src.analytics.main"

def test_health_check():
    """Tests the basic system health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "Analytics Service"}

# ===========================================================================
# LIFESPAN TESTS (Startup / Shutdown)
# ===========================================================================

@patch(f"{MAIN}.connect_with_retry", AsyncMock())
@patch(f"{MAIN}.connect_redis", AsyncMock())
@patch(f"{MAIN}.register_app_routes", AsyncMock())
@patch(f"{MAIN}.close_auth_client", AsyncMock())
@patch(f"{MAIN}.disconnect_redis", AsyncMock())
@patch(f"{MAIN}.db.disconnect", AsyncMock())
def test_lifespan_success():
    """
    Using TestClient in a 'with' block automatically triggers the lifespan
    startup (yield) and shutdown sequences. We mock all external services
    to ensure it runs instantly without needing a real DB/Redis.
    """
    with TestClient(app):
        # The app has fully started up here
        pass 
    # The app has fully shut down here


@patch(f"{MAIN}.connect_with_retry", AsyncMock())
@patch(f"{MAIN}.connect_redis", AsyncMock(side_effect=Exception("Redis timeout")))
@patch(f"{MAIN}.register_app_routes", AsyncMock())
@patch(f"{MAIN}.close_auth_client", AsyncMock())
@patch(f"{MAIN}.disconnect_redis", AsyncMock())
@patch(f"{MAIN}.db.disconnect", AsyncMock())
def test_lifespan_redis_failure():
    """
    Tests the try/except block in the lifespan manager. 
    If Redis fails to connect, the app should still boot up successfully.
    """
    with TestClient(app):
        # App should still start up fine, catching the Exception and printing the warning
        pass