"""
test_service.py
Unit tests for src/analytics/service.py

Covers every method, every data-mapping branch, every fallback,
and all error propagation paths.

Functions under test:
  - get_recent_reviews_list: maps raw Prisma review rows → RecentReview schemas
  - get_leaderboard_list: ranks wallet rows → LeaderboardEntry schemas
  - get_platform_stats: parallel query aggregation via asyncio.gather → PlatformStats
"""

import sys
import types
import os
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# 2. STRICT ABSOLUTE IMPORTS
# This ensures Python finds the real files regardless of where pytest is sitting
from src.analytics.tests.conftest import (  
    make_user, make_raw_review, make_reviewer,
    make_employee, make_wallet_entry,
)
from src.analytics.service import (  
    get_recent_reviews_list,
    get_leaderboard_list,
    get_platform_stats,
)

# Set the SVC constant to the full path so the 'patch' decorator knows exactly where to look
SVC = "src.analytics.service"


# ===========================================================================
# GET RECENT REVIEWS LIST
# ===========================================================================

class TestGetRecentReviewsList:
    """Tests for get_recent_reviews_list()"""

    # --- Happy path / data mapping ---

    @pytest.mark.asyncio
    async def test_returns_mapped_reviews(self):
        raw = [
            make_raw_review(reviewer_username="alice", tags=["COOL"], comment="Excellent"),
            make_raw_review(reviewer_username="bob", tags=["OK"], comment="OK"),
        ]

        with patch(f"{SVC}.get_recent_reviews", AsyncMock(return_value=raw)):
            result = await get_recent_reviews_list("emp-1")

        assert len(result) == 2
        assert result[0].reviewer_name == "alice"
        assert result[0].tags == ["COOL"]
        assert result[0].comment == "Excellent"
        assert result[1].reviewer_name == "bob"
        assert result[1].tags == ["OK"]

    @pytest.mark.asyncio
    async def test_empty_reviews_returns_empty_list(self):
        with patch(f"{SVC}.get_recent_reviews", AsyncMock(return_value=[])):
            result = await get_recent_reviews_list("emp-1")

        assert result == []

    @pytest.mark.asyncio
    async def test_review_fields_are_passed_correctly(self):
        review_id = str(uuid4())
        review_at = datetime(2026, 1, 20, 8, 30, tzinfo=timezone.utc)
        raw = [make_raw_review(
            review_id=review_id, tags=["HELPFUL"],
            comment="Needs improvement", review_at=review_at,
        )]

        with patch(f"{SVC}.get_recent_reviews", AsyncMock(return_value=raw)):
            result = await get_recent_reviews_list("emp-1")

        assert str(result[0].review_id) == review_id
        assert result[0].tags == ["HELPFUL"]
        assert result[0].comment == "Needs improvement"
        assert result[0].review_at == review_at

    # --- Fallback / edge cases ---

    @pytest.mark.asyncio
    async def test_missing_reviewer_defaults_to_unknown(self):
        """When reviewer relation is None, reviewer_name should be 'Unknown'."""
        raw = [make_raw_review()]
        raw[0].employees_reviews_reviewer_idToemployees = None

        with patch(f"{SVC}.get_recent_reviews", AsyncMock(return_value=raw)):
            result = await get_recent_reviews_list("emp-1")

        assert result[0].reviewer_name == "Unknown"

    # --- Query arguments ---

    @pytest.mark.asyncio
    async def test_calls_query_with_correct_args(self):
        mock = AsyncMock(return_value=[])

        with patch(f"{SVC}.get_recent_reviews", mock):
            await get_recent_reviews_list("emp-42")

        mock.assert_called_once_with("emp-42", limit=5)

    # --- Error propagation ---

    @pytest.mark.asyncio
    async def test_query_failure_propagates(self):
        with patch(f"{SVC}.get_recent_reviews",
                   AsyncMock(side_effect=RuntimeError("query failed"))):
            with pytest.raises(RuntimeError, match="query failed"):
                await get_recent_reviews_list("emp-1")

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self):
        with patch(f"{SVC}.get_recent_reviews",
                   AsyncMock(side_effect=ConnectionError("DB unreachable"))):
            with pytest.raises(ConnectionError, match="DB unreachable"):
                await get_recent_reviews_list("emp-1")


# ===========================================================================
# GET LEADERBOARD LIST
# ===========================================================================

class TestGetLeaderboardList:
    """Tests for get_leaderboard_list()"""

    # --- Happy path / ranking ---

    @pytest.mark.asyncio
    async def test_returns_ranked_entries(self):
        entries = [
            make_wallet_entry(username="alice", total_earned_points=500),
            make_wallet_entry(username="bob", total_earned_points=300),
            make_wallet_entry(username="carol", total_earned_points=100),
        ]

        with patch(f"{SVC}.get_leaderboard", AsyncMock(return_value=entries)):
            result = await get_leaderboard_list()

        assert len(result) == 3
        assert result[0].rank == 1
        assert result[0].username == "alice"
        assert result[0].total_earned_points == 500
        assert result[1].rank == 2
        assert result[2].rank == 3

    @pytest.mark.asyncio
    async def test_empty_leaderboard(self):
        with patch(f"{SVC}.get_leaderboard", AsyncMock(return_value=[])):
            result = await get_leaderboard_list()

        assert result == []

    @pytest.mark.asyncio
    async def test_department_mapped_correctly(self):
        entries = [make_wallet_entry(department_name="Finance")]

        with patch(f"{SVC}.get_leaderboard", AsyncMock(return_value=entries)):
            result = await get_leaderboard_list()

        assert result[0].department == "Finance"

    # --- Fallback / edge cases ---

    @pytest.mark.asyncio
    async def test_missing_employee_uses_fallbacks(self):
        """When employee relation is None, username='Unknown', department='N/A'."""
        w = MagicMock()
        w.employee_id = str(uuid4())
        w.total_earned_points = 200
        w.employees_wallets_employee_idToemployees = None

        with patch(f"{SVC}.get_leaderboard", AsyncMock(return_value=[w])):
            result = await get_leaderboard_list()

        assert result[0].username == "Unknown"
        assert result[0].department == "N/A"
        assert str(result[0].employee_id) == w.employee_id

    @pytest.mark.asyncio
    async def test_missing_department_defaults_to_na(self):
        """When department relation is None, department should be 'N/A'."""
        emp = make_employee(username="dave")
        emp.departments_employees_department_idTodepartments = None
        w = MagicMock()
        w.employee_id = emp.employee_id
        w.total_earned_points = 150
        w.employees_wallets_employee_idToemployees = emp

        with patch(f"{SVC}.get_leaderboard", AsyncMock(return_value=[w])):
            result = await get_leaderboard_list()

        assert result[0].department == "N/A"

    # --- Query arguments ---

    @pytest.mark.asyncio
    async def test_calls_query_with_limit_10(self):
        mock = AsyncMock(return_value=[])

        with patch(f"{SVC}.get_leaderboard", mock):
            await get_leaderboard_list()

        mock.assert_called_once_with(limit=10)

    # --- Error propagation ---

    @pytest.mark.asyncio
    async def test_query_failure_propagates(self):
        with patch(f"{SVC}.get_leaderboard",
                   AsyncMock(side_effect=RuntimeError("timeout"))):
            with pytest.raises(RuntimeError, match="timeout"):
                await get_leaderboard_list()


# ===========================================================================
# GET PLATFORM STATS
# ===========================================================================

class TestGetPlatformStats:
    """Tests for get_platform_stats()"""

    # --- Shared helper: patches all 11 queries at once ---

    async def _call_with_mocks(
        self,
        user_points=1000, pts_this=200, pts_last=150,
        rewards_total=50, rewards_this=10, rewards_last=8,
        reviews_total=30, reviews_this=5, reviews_last=3,
        active_now=42, active_last=38,
    ):
        with patch(f"{SVC}.get_user_total_points", AsyncMock(return_value=user_points)), \
             patch(f"{SVC}.get_user_points_earned_this_month", AsyncMock(return_value=pts_this)), \
             patch(f"{SVC}.get_user_points_earned_last_month", AsyncMock(return_value=pts_last)), \
             patch(f"{SVC}.get_user_total_rewards_redeemed", AsyncMock(return_value=rewards_total)), \
             patch(f"{SVC}.get_user_rewards_redeemed_this_month", AsyncMock(return_value=rewards_this)), \
             patch(f"{SVC}.get_user_rewards_redeemed_last_month", AsyncMock(return_value=rewards_last)), \
             patch(f"{SVC}.get_user_total_reviews", AsyncMock(return_value=reviews_total)), \
             patch(f"{SVC}.get_user_reviews_this_month", AsyncMock(return_value=reviews_this)), \
             patch(f"{SVC}.get_user_reviews_last_month", AsyncMock(return_value=reviews_last)), \
             patch(f"{SVC}.get_active_users_count", AsyncMock(return_value=active_now)), \
             patch(f"{SVC}.get_active_users_count_last_month", AsyncMock(return_value=active_last)):
            return await get_platform_stats("emp-1")

    # --- Individual metric assertions ---

    @pytest.mark.asyncio
    async def test_total_points_metric(self):
        result = await self._call_with_mocks(user_points=5000, pts_this=800, pts_last=600)

        assert result.total_points.value == 5000
        assert result.total_points.this_month == 800
        assert result.total_points.last_month == 600

    @pytest.mark.asyncio
    async def test_rewards_redeemed_metric(self):
        result = await self._call_with_mocks(rewards_total=100, rewards_this=20, rewards_last=15)

        assert result.rewards_redeemed.value == 100
        assert result.rewards_redeemed.this_month == 20
        assert result.rewards_redeemed.last_month == 15

    @pytest.mark.asyncio
    async def test_reviews_received_metric(self):
        result = await self._call_with_mocks(reviews_total=50, reviews_this=10, reviews_last=7)

        assert result.reviews_received.value == 50
        assert result.reviews_received.this_month == 10
        assert result.reviews_received.last_month == 7

    @pytest.mark.asyncio
    async def test_active_users_metric(self):
        """active_users.value and this_month are both the current active count."""
        result = await self._call_with_mocks(active_now=100, active_last=90)

        assert result.active_users.value == 100
        assert result.active_users.this_month == 100
        assert result.active_users.last_month == 90

    # --- Edge cases ---

    @pytest.mark.asyncio
    async def test_all_zeros(self):
        result = await self._call_with_mocks(
            user_points=0, pts_this=0, pts_last=0,
            rewards_total=0, rewards_this=0, rewards_last=0,
            reviews_total=0, reviews_this=0, reviews_last=0,
            active_now=0, active_last=0,
        )

        assert result.total_points.value == 0
        assert result.total_points.this_month == 0
        assert result.total_points.last_month == 0
        assert result.rewards_redeemed.value == 0
        assert result.reviews_received.value == 0
        assert result.active_users.value == 0

    @pytest.mark.asyncio
    async def test_returns_platform_stats_type(self):
        from src.analytics.schemas import PlatformStats
        result = await self._call_with_mocks()

        assert isinstance(result, PlatformStats)

    # --- Query arguments ---

    @pytest.mark.asyncio
    async def test_employee_scoped_queries_receive_employee_id(self):
        """All employee-scoped queries should receive the employee_id arg."""
        pts_mock      = AsyncMock(return_value=0)
        pts_this_mock = AsyncMock(return_value=0)
        pts_last_mock = AsyncMock(return_value=0)

        with patch(f"{SVC}.get_user_total_points", pts_mock), \
             patch(f"{SVC}.get_user_points_earned_this_month", pts_this_mock), \
             patch(f"{SVC}.get_user_points_earned_last_month", pts_last_mock), \
             patch(f"{SVC}.get_user_total_rewards_redeemed", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_reviews", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count_last_month", AsyncMock(return_value=0)):
            await get_platform_stats("specific-emp-id")

        pts_mock.assert_called_once_with("specific-emp-id")
        pts_this_mock.assert_called_once_with("specific-emp-id")
        pts_last_mock.assert_called_once_with("specific-emp-id")

    @pytest.mark.asyncio
    async def test_global_queries_called_without_employee_id(self):
        """active_users queries are platform-wide — no employee_id arg."""
        active_mock      = AsyncMock(return_value=0)
        active_last_mock = AsyncMock(return_value=0)

        with patch(f"{SVC}.get_user_total_points", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_points_earned_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_points_earned_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_rewards_redeemed", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_reviews", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count", active_mock), \
             patch(f"{SVC}.get_active_users_count_last_month", active_last_mock):
            await get_platform_stats("emp-1")

        active_mock.assert_called_once_with()
        active_last_mock.assert_called_once_with()

    # --- Error propagation (asyncio.gather) ---

    @pytest.mark.asyncio
    async def test_single_query_exception_propagates_from_gather(self):
        """If one query in asyncio.gather fails, the exception should propagate."""
        with patch(f"{SVC}.get_user_total_points",
                   AsyncMock(side_effect=RuntimeError("DB down"))), \
             patch(f"{SVC}.get_user_points_earned_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_points_earned_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_rewards_redeemed", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_reviews", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count_last_month", AsyncMock(return_value=0)):
            with pytest.raises(RuntimeError, match="DB down"):
                await get_platform_stats("emp-1")

    @pytest.mark.asyncio
    async def test_connection_error_propagates_from_gather(self):
        """A connection-level error in any query should bubble up."""
        with patch(f"{SVC}.get_user_total_points", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_points_earned_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_points_earned_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_rewards_redeemed", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_rewards_redeemed_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_total_reviews", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_this_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_user_reviews_last_month", AsyncMock(return_value=0)), \
             patch(f"{SVC}.get_active_users_count",
                   AsyncMock(side_effect=ConnectionError("lost connection"))), \
             patch(f"{SVC}.get_active_users_count_last_month", AsyncMock(return_value=0)):
            with pytest.raises(ConnectionError, match="lost connection"):
                await get_platform_stats("emp-1")
