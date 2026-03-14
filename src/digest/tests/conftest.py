"""
conftest.py — shared fixtures and stubs for digest tests.
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

# Stub Prisma class
class Prisma:
    pass
sys.modules["src.prisma"].Prisma = Prisma

# Stub common cache
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

# Stub EmailSender
_notif_email_stub = types.ModuleType("src.notifications.email_sender")
sys.modules["src.notifications.email_sender"] = _notif_email_stub
class EmailSender:
    pass
_notif_email_stub.EmailSender = EmailSender

# Stub digest queries and email_builder to avoid real DB/logic
_digest_queries_stub = types.ModuleType("src.digest.queries")
sys.modules["src.digest.queries"] = _digest_queries_stub
_digest_queries_stub.fetch_weekly_digest_data = AsyncMock()

_digest_builder_stub = types.ModuleType("src.digest.email_builder")
sys.modules["src.digest.email_builder"] = _digest_builder_stub
_digest_builder_stub.build_digest_html = MagicMock(return_value=("Subject", "<html></html>"))

@pytest.fixture
def db():
    return mock_db

@pytest.fixture
def mock_sender():
    sender = MagicMock()
    sender.send_notification_email = AsyncMock()
    return sender
