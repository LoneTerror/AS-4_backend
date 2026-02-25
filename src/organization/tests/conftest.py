"""
Shared pytest fixtures and configuration for both auth and organization services.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


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
        "employee_id": uuid4(),
        "designation_id": uuid4(),
        "department_id": uuid4(),
        "manager_id": uuid4(),
        "department_type_id": uuid4(),
    }


# ---------------------------------------------------------------------------
# JWT payload fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_jwt_payload(sample_employee_id):
    return {
        "sub": sample_employee_id,
        "email": "user@example.com",
        "roles": ["EMPLOYEE"],
        "department_id": str(uuid4()),
    }


@pytest.fixture
def admin_jwt_payload(sample_employee_id):
    return {
        "sub": sample_employee_id,
        "email": "admin@example.com",
        "roles": ["SUPER_ADMIN"],
        "department_id": str(uuid4()),
    }
