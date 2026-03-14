"""
conftest.py — shared fixtures and stubs for notifications tests.
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# 1. Stub dependencies BEFORE any project imports
# ---------------------------------------------------------------------------
_prisma_stub = types.ModuleType("src.prisma")
sys.modules["src.prisma"] = _prisma_stub
_prisma_client_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_client_stub

_prisma_client_stub.db = MagicMock()
mock_db = _prisma_client_stub.db

# Ensure common DB methods are AsyncMocks
_prisma_client_stub.db.find_many = AsyncMock()
_prisma_client_stub.db.find_unique = AsyncMock()
_prisma_client_stub.db.find_first = AsyncMock()
_prisma_client_stub.db.create = AsyncMock()
_prisma_client_stub.db.update = AsyncMock()
_prisma_client_stub.db.delete = AsyncMock()
_prisma_client_stub.db.count = AsyncMock()
_prisma_client_stub.db.update_many = AsyncMock()
_prisma_client_stub.db.delete_many = AsyncMock()
_prisma_client_stub.db.tx = AsyncMock()
_prisma_client_stub.connect_with_retry = AsyncMock()

# Ensure specific table methods are AsyncMocks
mock_db.notifications.create = AsyncMock()
mock_db.employees.find_many = AsyncMock()
mock_db.notifications.find_many = AsyncMock()
mock_db.notifications.count = AsyncMock()
mock_db.notifications.find_first = AsyncMock()
mock_db.notifications.update = AsyncMock()
mock_db.notifications.update_many = AsyncMock()

# Stub Prisma class for type hinting if needed
class Prisma:
    pass
sys.modules["src.prisma"].Prisma = Prisma

# Stub common cache
_common_cache_stub = types.ModuleType("src.common.cache")
sys.modules["src.common.cache"] = _common_cache_stub
_common_cache_stub.cache_get = AsyncMock(return_value=None)
_common_cache_stub.cache_set = AsyncMock()
_common_cache_stub.cache_delete = AsyncMock()
_common_cache_stub.invalidate_pattern = AsyncMock()

# TTL and L1 constants
_common_cache_stub.TTL_VOLATILE = 60
_common_cache_stub.L1_VOLATILE = 30
_common_cache_stub.TTL_SHORT = 300
_common_cache_stub.L1_SHORT = 60
_common_cache_stub.TTL_MEDIUM = 3600
_common_cache_stub.L1_MEDIUM = 300
_common_cache_stub.TTL_PERMANENT = 86400
_common_cache_stub.L1_PERMANENT = 3600

# Stub notifications cache for enqueue_notification
_cache_stub = types.ModuleType("src.notifications.cache")
sys.modules["src.notifications.cache"] = _cache_stub
_cache_stub.enqueue_notification = AsyncMock()

@pytest.fixture
def db():
    return mock_db
