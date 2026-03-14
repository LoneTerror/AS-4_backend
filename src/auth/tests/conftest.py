"""
conftest.py — shared fixtures and stubs for auth tests.
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
mock_db = MagicMock()
_prisma_stub.db = mock_db

# Mock common DB methods as AsyncMocks
mock_db.employees.find_first = AsyncMock()
mock_db.refresh_tokens.create = AsyncMock()

# Stub core security to avoid real bcrypt/jwt during unit tests
sys.modules["src.core.security"] = MagicMock()
sec = sys.modules["src.core.security"]
sec.verify_password = MagicMock(return_value=True)
sec.hash_password = MagicMock(return_value="hashed_pass")
sec.create_access_token = MagicMock(return_value="access_token")
sec.hash_refresh_token = MagicMock(return_value="hashed_refresh")
sec.ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Stub email utils
sys.modules["src.core.email_utils"] = MagicMock()

@pytest.fixture
def db():
    return mock_db

@pytest.fixture
def mock_sec():
    return sys.modules["src.core.security"]

# ---------------------------------------------------------------------------
# 2. Mock Data Helpers
# ---------------------------------------------------------------------------
def make_employee(employee_id="emp-1", username="testuser", email="test@example.com", password_hash="hashed_password"):
    emp = MagicMock()
    emp.employee_id = employee_id
    emp.username = username
    emp.email = email
    emp.password_hash = password_hash
    emp.designation_id = "des-1"
    emp.department_id = "dept-1"
    # Mock the roles relation
    emp.employee_roles_employee_roles_employee_idToemployees = []
    return emp

@pytest.fixture
def sample_user():
    return make_employee()
