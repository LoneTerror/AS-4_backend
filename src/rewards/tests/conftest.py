import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# Adjust imports to match your actual file names (e.g., api.py vs router.py)
from src.rewards.router import router, get_db
from src.rewards.dependencies import CurrentUser, get_current_user

@pytest.fixture
def mock_db():
    """Creates a standalone mock of the Prisma client."""
    db_mock = AsyncMock()
    
    # Mock the db.tx() context manager specifically
    mock_tx_context = AsyncMock()
    mock_tx_context.__aenter__.return_value = mock_tx_context
    db_mock.tx.return_value = mock_tx_context
    
    return db_mock

@pytest.fixture
def admin_user():
    return CurrentUser(
        id="admin-123",
        email="admin@company.com",
        roles=["HR_ADMIN"]
    )

@pytest.fixture
def employee_user():
    return CurrentUser(
        id="emp-456",
        email="employee@company.com",
        roles=["EMPLOYEE"]
    )

@pytest.fixture
def app_client(mock_db, admin_user):
    """FastAPI TestClient with overridden dependencies."""
    app = FastAPI()
    app.include_router(router)
    
    # 1. Override the DB dependency to use our mock
    app.dependency_overrides[get_db] = lambda: mock_db
    
    # 2. Override the current user to bypass the httpx auth call
    app.dependency_overrides[get_current_user] = lambda: admin_user
    
    return TestClient(app)