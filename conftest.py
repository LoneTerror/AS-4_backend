"""
ROOT conftest.py  —  emp_r&r/conftest.py

IMPORTANT: This file must live at the project ROOT (same level as pyproject.toml),
NOT inside any service folder. pytest loads it before collecting any test files,
so the SECRET_KEY env variable is set before src.core.security is imported.
"""

import os
import sys
import pytest
import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

# ---------------------------------------------------------------------------
# FIX: Set SECRET_KEY before ANY src.* module is imported.
# src/core/security.py raises RuntimeError if this is missing at import time.
# ---------------------------------------------------------------------------
os.environ.setdefault("SECRET_KEY", "test-secret-key-minimum-32-characters-long!!")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
os.environ.setdefault("SMTP_HOST",     "smtp.gmail.com")
os.environ.setdefault("SMTP_PORT",     "587")
os.environ.setdefault("SMTP_USERNAME", "test@example.com")
os.environ.setdefault("SMTP_PASSWORD", "test-password")
os.environ.setdefault("FRONTEND_URL",  "http://localhost:3000")


# ---------------------------------------------------------------------------
# Event loop policy for asyncio tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Shared employee / user fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_employee_id():
    return str(uuid4())


@pytest.fixture
def super_admin_user():
    """A CurrentUser (auth service) with SUPER_ADMIN role."""
    try:
        from src.auth.dependencies import CurrentUser
        return CurrentUser(id=str(uuid4()), roles=["SUPER_ADMIN"])
    except ImportError:
        return MagicMock(id=str(uuid4()), roles=["SUPER_ADMIN"])


@pytest.fixture
def hr_admin_user():
    """A CurrentUser (auth service) with HR_ADMIN role."""
    try:
        from src.auth.dependencies import CurrentUser
        return CurrentUser(id=str(uuid4()), roles=["HR_ADMIN"])
    except ImportError:
        return MagicMock(id=str(uuid4()), roles=["HR_ADMIN"])


@pytest.fixture
def employee_user():
    """A CurrentEmployee (organization service) with EMPLOYEE role."""
    try:
        from src.organization.dependencies import CurrentEmployee
        return CurrentEmployee(id=str(uuid4()), roles=["EMPLOYEE"], email="emp@test.com")
    except ImportError:
        return MagicMock(id=str(uuid4()), roles=["EMPLOYEE"], email="emp@test.com")


@pytest.fixture
def sample_uuids():
    return {
        "employee_id":      uuid4(),
        "designation_id":   uuid4(),
        "department_id":    uuid4(),
        "manager_id":       uuid4(),
        "department_type_id": uuid4(),
    }


# ---------------------------------------------------------------------------
# JWT payload fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_jwt_payload(sample_employee_id):
    return {
        "sub":           sample_employee_id,
        "email":         "user@example.com",
        "roles":         ["EMPLOYEE"],
        "department_id": str(uuid4()),
    }


@pytest.fixture
def admin_jwt_payload(sample_employee_id):
    return {
        "sub":           sample_employee_id,
        "email":         "admin@example.com",
        "roles":         ["SUPER_ADMIN"],
        "department_id": str(uuid4()),
    }