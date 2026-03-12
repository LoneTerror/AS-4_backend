"""
conftest.py — shared fixtures and stubs for employees tests.
"""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel
from typing import List, Optional

# ---------------------------------------------------------------------------
# 1. Stub dependencies BEFORE any project imports
# ---------------------------------------------------------------------------
_prisma_stub = types.ModuleType("src.prisma.client")
sys.modules["src.prisma.client"] = _prisma_stub
_prisma_stub.db = MagicMock()
mock_db = _prisma_stub.db

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

# Ensure specific table methods are AsyncMocks
mock_db.employees.find_many = AsyncMock()
mock_db.employees.count = AsyncMock()
mock_db.employees.find_unique = AsyncMock()
mock_db.employees.create = AsyncMock()
mock_db.employees.update = AsyncMock()

# Stub cache
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

# Stub notifications redis client if needed
_notif_redis_stub = types.ModuleType("src.notifications.redis_client")
sys.modules["src.notifications.redis_client"] = _notif_redis_stub
_notif_redis_stub.get_redis = MagicMock(return_value=None)

@pytest.fixture
def db():
    return mock_db

from uuid import uuid4
from datetime import date, datetime, timezone

def make_employee_row(employee_id=None, username="testuser"):
    emp_id = employee_id or str(uuid4())
    emp = MagicMock()
    emp.employee_id = emp_id
    emp.username = username
    emp.email = f"{username}@example.com"
    emp.date_of_joining = date.today()
    emp.created_at = datetime.now(timezone.utc)
    emp.updated_at = datetime.now(timezone.utc)
    
    # Mock relations
    emp.departments_employees_department_idTodepartments = None
    emp.designations_employees_designation_idTodesignations = None
    emp.status_master_employees_status_idTostatus_master = None
    emp.employees_employees_manager_idToemployees = None
    
    return emp
