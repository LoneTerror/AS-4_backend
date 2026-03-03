import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# 1. CRITICAL: Stub Prisma BEFORE any other project imports
# ---------------------------------------------------------------------------
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
_prisma_stub.db = MagicMock()
_prisma_stub.connect_with_retry = AsyncMock()

# Now it is safe to import your project modules
from src.rewards.router import router, get_db
from src.rewards.dependencies import CurrentUser, get_current_user

@pytest.fixture
def mock_db():
    """Creates a standalone mock of the Prisma client."""
    db_mock = AsyncMock()
    
    # Mock the db.tx() context manager specifically for Rewards transactions
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
def app_client(mock_db, admin_user):
    """FastAPI TestClient with overridden dependencies."""
    app = FastAPI()
    app.include_router(router)
    
    # Override dependencies to use the mocks
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    
    return TestClient(app)