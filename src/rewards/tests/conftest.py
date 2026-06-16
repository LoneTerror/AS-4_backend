import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI


_cache_stub = types.ModuleType("src.common.cache")
sys.modules["src.common.cache"] = _cache_stub
_cache_stub.cache_get = AsyncMock(return_value=None)
_cache_stub.cache_set = AsyncMock()
_cache_stub.cache_delete = AsyncMock()
_cache_stub.invalidate_pattern = AsyncMock()

# TTL and L1 constants
_cache_stub.TTL_VOLATILE = 60
_cache_stub.L1_VOLATILE = 30
_cache_stub.TTL_SHORT = 300
_cache_stub.L1_SHORT = 60
_cache_stub.TTL_MEDIUM = 3600
_cache_stub.L1_MEDIUM = 300
_cache_stub.TTL_PERMANENT = 86400
_cache_stub.L1_PERMANENT = 3600

# ---------------------------------------------------------------------------
# 1. CRITICAL: Stub Prisma BEFORE any other project imports
# ---------------------------------------------------------------------------
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
_prisma_stub.db = MagicMock()

# Ensure common DB methods are AsyncMocks
_prisma_stub.db.find_many = AsyncMock()
_prisma_stub.db.find_unique = AsyncMock()
_prisma_stub.db.find_first = AsyncMock()
_prisma_stub.db.create = AsyncMock()
_prisma_stub.db.update = AsyncMock()
_prisma_stub.db.delete = AsyncMock()
_prisma_stub.db.count = AsyncMock()
_prisma_stub.db.update_many = AsyncMock()
_prisma_stub.db.delete_many = AsyncMock()
_prisma_stub.db.tx = AsyncMock()
_prisma_stub.connect_with_retry = AsyncMock()

# Ensure nested models return AsyncMocks for their methods
_prisma_stub.db.route_permissions.find_many = AsyncMock(return_value=[])
_prisma_stub.db.roles.find_many = AsyncMock(return_value=[])

# Now it is safe to import your project modules
from src.rewards.router import router, get_db
from src.common.dependencies import CurrentUser, get_current_user

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
        roles=["SUPER_ADMIN", "HR_ADMIN"]
    )

@pytest.fixture
def app_client(mock_db, admin_user):
    """FastAPI TestClient with overridden dependencies."""
    app = FastAPI()
    app.include_router(router, prefix="/aabhar/v1/rewards")
    
    # Override dependencies to use the mocks
    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: admin_user
    
    return TestClient(app)