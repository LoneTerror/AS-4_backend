"""Tests for GET /v1/dashboard/summary (endpoint-level)."""
import pytest
from unittest.mock import AsyncMock, patch
from contextlib import ExitStack
from httpx import AsyncClient, ASGITransport

from src.analytics.main import app
from src.analytics.dependencies import CurrentUser, get_current_user
from src.analytics.tests.conftest import (
    make_employee,
    make_review,
    make_leaderboard_entry,
)

Q = "src.analytics.service"
TEST_EMP_ID = "550e8400-e29b-41d4-a716-446655440000"


def _fake_user():
    async def inner():
        return CurrentUser(
            id=TEST_EMP_ID, email="test@company.com",
            roles=["EMPLOYEE"], department_id="dept-1",
        )
    return inner


def _query_mocks(**overrides):
    defaults = {
        "get_employee_with_details": AsyncMock(
            return_value=make_employee(employee_id=TEST_EMP_ID)
        ),
        "get_recent_reviews": AsyncMock(return_value=[make_review()]),
        "get_leaderboard": AsyncMock(return_value=[
            make_leaderboard_entry(username="alice", total_earned_points=5000),
        ]),
        "get_user_total_points": AsyncMock(return_value=3000),
        "get_user_points_earned_this_month": AsyncMock(return_value=500),
        "get_user_points_earned_last_month": AsyncMock(return_value=400),
        "get_user_total_rewards_redeemed": AsyncMock(return_value=45),
        "get_user_rewards_redeemed_this_month": AsyncMock(return_value=10),
        "get_user_rewards_redeemed_last_month": AsyncMock(return_value=8),
        "get_user_total_reviews": AsyncMock(return_value=120),
        "get_user_reviews_this_month": AsyncMock(return_value=30),
        "get_user_reviews_last_month": AsyncMock(return_value=25),
        "get_active_users_count": AsyncMock(return_value=150),
        "get_active_users_count_last_month": AsyncMock(return_value=120),
    }
    defaults.update(overrides)
    return defaults


def _ctx(m):
    stack = ExitStack()
    for name, mock in m.items():
        stack.enter_context(patch(f"{Q}.{name}", mock))
    return stack


@pytest.mark.asyncio
async def test_endpoint_returns_200():
    app.dependency_overrides[get_current_user] = _fake_user()

    with _ctx(_query_mocks()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/dashboard/summary")

    assert resp.status_code == 200
    body = resp.json()

    for key in ("employee", "recent_reviews", "leaderboard", "platform_stats"):
        assert key in body

    assert body["employee"]["username"] == "john.doe"
    assert body["platform_stats"]["total_points"]["value"] == 3000
    assert body["platform_stats"]["active_users"]["value"] == 150

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_endpoint_requires_auth():
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/v1/dashboard/summary")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_endpoint_returns_404_when_employee_missing():
    app.dependency_overrides[get_current_user] = _fake_user()

    mocks = _query_mocks(get_employee_with_details=AsyncMock(return_value=None))
    with _ctx(mocks):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get("/v1/dashboard/summary")

    assert resp.status_code == 404
    app.dependency_overrides.clear()
