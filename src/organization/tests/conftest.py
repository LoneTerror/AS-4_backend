"""
conftest.py — shared fixtures and stubs for organization tests.
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# 1. Stub dependencies BEFORE any project imports
# ---------------------------------------------------------------------------
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
mock_db = MagicMock()
_prisma_stub.db = mock_db

# Stub common DB methods
mock_db.departments.find_many = AsyncMock()
mock_db.departments.count = AsyncMock()

# Stub cache
_cache_stub = types.ModuleType("src.common.cache")
sys.modules["src.common.cache"] = _cache_stub
_cache_stub.cache_get = AsyncMock(return_value=None)
_cache_stub.cache_set = AsyncMock()
_cache_stub.cache_delete = AsyncMock()
_cache_stub.invalidate_pattern = AsyncMock()

@pytest.fixture
def db():
    return mock_db
