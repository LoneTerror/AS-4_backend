"""Tests for src.analytics.service — get_dashboard_summary()."""
import pytest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from contextlib import ExitStack
from fastapi import HTTPException

from src.analytics.tests.conftest import (
    make_employee,
    make_review,
    make_leaderboard_entry,
)

Q = "src.analytics.service"


def _patches(**overrides):
    defaults = {
        "get_employee_with_details": AsyncMock(return_value=make_employee()),
        "get_recent_reviews": AsyncMock(
            return_value=[make_review(), make_review(reviewer_username="bob", rating=4)]
        ),
        "get_leaderboard": AsyncMock(return_value=[
            make_leaderboard_entry(username="alice", total_earned_points=5000),
            make_leaderboard_entry(username="bob", total_earned_points=4000),
        ]),
        # Total points
        "get_user_total_points": AsyncMock(return_value=3000),
        "get_user_points_earned_this_month": AsyncMock(return_value=500),
        "get_user_points_earned_last_month": AsyncMock(return_value=400),
        # Rewards (user-specific)
        "get_user_total_rewards_redeemed": AsyncMock(return_value=45),
        "get_user_rewards_redeemed_this_month": AsyncMock(return_value=10),
        "get_user_rewards_redeemed_last_month": AsyncMock(return_value=8),
        # Reviews (user-specific)
        "get_user_total_reviews": AsyncMock(return_value=120),
        "get_user_reviews_this_month": AsyncMock(return_value=30),
        "get_user_reviews_last_month": AsyncMock(return_value=25),
        # Active users
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


# ── Happy path ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_dashboard_summary():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches()):
        result = await get_dashboard_summary("emp-123")

    # Employee
    assert result["employee"]["username"] == "john.doe"
    assert result["employee"]["designation"] == "Senior Developer"

    # Reviews
    assert len(result["recent_reviews"]) == 2

    # Leaderboard
    assert result["leaderboard"][0]["rank"] == 1
    assert result["leaderboard"][0]["username"] == "alice"

    # Platform stats — value + growth_percent
    ps = result["platform_stats"]

    assert ps["total_points"]["value"] == 3000
    assert ps["total_points"]["growth_percent"] == 25.0  # (500-400)/400

    assert ps["rewards_redeemed"]["value"] == 45
    assert ps["rewards_redeemed"]["growth_percent"] == 25.0  # (10-8)/8

    assert ps["reviews_received"]["value"] == 120
    assert ps["reviews_received"]["growth_percent"] == 20.0  # (30-25)/25

    assert ps["active_users"]["value"] == 150
    assert ps["active_users"]["growth_percent"] == 25.0  # (150-120)/120


# ── Employee not found ────────────────────────────────────────

@pytest.mark.asyncio
async def test_employee_not_found_raises_404():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches(get_employee_with_details=AsyncMock(return_value=None))):
        with pytest.raises(HTTPException) as exc:
            await get_dashboard_summary("ghost")
    assert exc.value.status_code == 404


# ── Missing designation / department ──────────────────────────

@pytest.mark.asyncio
async def test_missing_designation_department_falls_back():
    from src.analytics.service import get_dashboard_summary

    emp = SimpleNamespace(
        employee_id="emp-123", username="john.doe",
        designations_employees_designation_idTodesignations=None,
        departments_employees_department_idTodepartments=None,
    )
    with _ctx(_patches(get_employee_with_details=AsyncMock(return_value=emp))):
        result = await get_dashboard_summary("emp-123")

    assert result["employee"]["designation"] == "N/A"
    assert result["employee"]["department"] == "N/A"


# ── Missing reviewer ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_reviewer_shows_unknown():
    from src.analytics.service import get_dashboard_summary

    review = SimpleNamespace(
        review_id="rev-1", rating=3, comment="Good job",
        review_at="2026-02-05T14:20:00Z",
        employees_reviews_reviewer_idToemployees=None,
    )
    with _ctx(_patches(get_recent_reviews=AsyncMock(return_value=[review]))):
        result = await get_dashboard_summary("emp-123")

    assert result["recent_reviews"][0]["reviewer_name"] == "Unknown"


# ── Empty leaderboard ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_leaderboard():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches(get_leaderboard=AsyncMock(return_value=[]))):
        result = await get_dashboard_summary("emp-123")

    assert result["leaderboard"] == []


# ── Growth edge cases ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_growth_zero_last_month_gives_100():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches(
        get_user_points_earned_this_month=AsyncMock(return_value=500),
        get_user_points_earned_last_month=AsyncMock(return_value=0),
    )):
        result = await get_dashboard_summary("emp-123")

    assert result["platform_stats"]["total_points"]["growth_percent"] == 100.0


@pytest.mark.asyncio
async def test_growth_both_zero_gives_0():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches(
        get_user_rewards_redeemed_this_month=AsyncMock(return_value=0),
        get_user_rewards_redeemed_last_month=AsyncMock(return_value=0),
    )):
        result = await get_dashboard_summary("emp-123")

    assert result["platform_stats"]["rewards_redeemed"]["growth_percent"] == 0.0


@pytest.mark.asyncio
async def test_growth_negative():
    from src.analytics.service import get_dashboard_summary

    with _ctx(_patches(
        get_user_reviews_this_month=AsyncMock(return_value=20),
        get_user_reviews_last_month=AsyncMock(return_value=40),
    )):
        result = await get_dashboard_summary("emp-123")

    assert result["platform_stats"]["reviews_received"]["growth_percent"] == -50.0
