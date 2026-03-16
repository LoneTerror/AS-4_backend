import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
import sys

# Import the module so we can test it
import src.analytics.queries as q

# Grab the globally mocked Prisma client from conftest
mock_prisma_client = sys.modules["src.prisma.client"]

@pytest.mark.asyncio
class TestAnalyticsQueries:

    # ===========================================================================
    # INTERNAL HELPERS
    # ===========================================================================
    async def test_helpers(self):
        # Test _zero
        assert await q._zero() == 0
        
        # Test _now
        now = q._now()
        assert now.tzinfo == timezone.utc

        # Test _month_range
        start, end = q._month_range(now)
        assert start.day == 1
        assert start.hour == 0
        assert end == start + relativedelta(months=1)

    # ===========================================================================
    # SHARED LOOKUPS
    # ===========================================================================
    async def test_get_employee_with_details(self):
        mock_prisma_client.db.employees.find_unique = AsyncMock(return_value="emp_data")
        res = await q.get_employee_with_details("e1")
        assert res == "emp_data"
        mock_prisma_client.db.employees.find_unique.assert_called_once()

    async def test_get_recent_reviews(self):
        mock_prisma_client.db.reviews.find_many = AsyncMock(return_value=["rev1", "rev2"])
        res = await q.get_recent_reviews("e1", 2)
        assert len(res) == 2

    async def test_get_leaderboard(self):
        mock_prisma_client.db.wallets.find_many = AsyncMock(return_value=["w1"])
        res = await q.get_leaderboard(5)
        assert res == ["w1"]

    async def test_get_active_users_count_found(self):
        mock_status = MagicMock()
        mock_status.status_id = "s1"
        mock_prisma_client.db.status_master.find_first = AsyncMock(return_value=mock_status)
        mock_prisma_client.db.employees.count = AsyncMock(return_value=42)
        
        assert await q.get_active_users_count() == 42
        assert await q.get_active_users_count_last_month() == 42

    async def test_get_active_users_count_not_found(self):
        # Trigger the 'if not s: return 0' branch
        mock_prisma_client.db.status_master.find_first = AsyncMock(return_value=None)
        assert await q.get_active_users_count() == 0
        assert await q.get_active_users_count_last_month() == 0

    # ===========================================================================
    # PLATFORM STATS BULK
    # ===========================================================================
    async def test_get_platform_stats_bulk_with_data(self):
        mock_wallet = MagicMock()
        mock_wallet.wallet_id = "w1"
        mock_wallet.available_points = 1000

        mock_credit = MagicMock()
        mock_credit.type_id = "c1"

        mock_txn = MagicMock()
        mock_txn.amount = 50

        # Setup mocks
        mock_prisma_client.db.wallets.find_first = AsyncMock(return_value=mock_wallet)
        mock_prisma_client.db.transaction_types.find_many = AsyncMock(return_value=[mock_credit])
        mock_prisma_client.db.transactions.find_many = AsyncMock(return_value=[mock_txn])
        mock_prisma_client.db.reward_history.count = AsyncMock(return_value=5)
        mock_prisma_client.db.reviews.count = AsyncMock(return_value=10)

        # We also need to mock the active user counts which are called internally
        with patch("src.analytics.queries.get_active_users_count", AsyncMock(return_value=100)), \
             patch("src.analytics.queries.get_active_users_count_last_month", AsyncMock(return_value=90)):
            
            res = await q.get_platform_stats_bulk("e1")
            
            assert res["user_points"] == 1000
            assert res["pts_this"] == 50  # 1 txn * 50
            assert res["rewards_total"] == 5
            assert res["active_now"] == 100

    async def test_get_platform_stats_bulk_no_wallet(self):
        # Trigger the 'else' branches where wallet is None
        mock_prisma_client.db.wallets.find_first = AsyncMock(return_value=None)
        mock_prisma_client.db.transaction_types.find_many = AsyncMock(return_value=[])
        mock_prisma_client.db.reviews.count = AsyncMock(return_value=0)
        
        with patch("src.analytics.queries.get_active_users_count", AsyncMock(return_value=0)), \
             patch("src.analytics.queries.get_active_users_count_last_month", AsyncMock(return_value=0)):
            
            res = await q.get_platform_stats_bulk("e_unknown")
            
            assert res["user_points"] == 0
            assert res["pts_this"] == 0
            assert res["rewards_total"] == 0

    # ===========================================================================
    # TEAM REPORTS
    # ===========================================================================
    async def test_team_report_queries(self):
        mock_prisma_client.db.departments.find_many = AsyncMock(return_value=[])
        assert await q.get_all_departments() == []

        mock_prisma_client.db.departments.find_unique = AsyncMock(return_value="dept")
        assert await q.get_department_by_id("d1") == "dept"

        mock_dept = MagicMock()
        mock_dept.department_id = "d1"
        mock_prisma_client.db.employees.find_many = AsyncMock(return_value=[])
        assert await q.get_employees_in_department(mock_dept) == []

        mock_emp = MagicMock()
        mock_emp.employee_id = "e1"
        mock_prisma_client.db.wallets.find_first = AsyncMock(return_value="wallet")
        assert await q.get_wallet_for_employee(mock_emp) == "wallet"

        mock_credit = MagicMock()
        mock_credit.type_id = "t1"
        mock_prisma_client.db.transaction_types.find_many = AsyncMock(return_value=[mock_credit])
        assert await q.get_credit_type_ids() == ["t1"]

        mock_wallet = MagicMock()
        mock_wallet.wallet_id = "w1"
        assert await q.get_points_this_month_for_wallet(mock_wallet, []) == 0 # Empty credit types

        mock_txn = MagicMock()
        mock_txn.amount = 100
        mock_prisma_client.db.transactions.find_many = AsyncMock(return_value=[mock_txn])
        assert await q.get_points_this_month_for_wallet(mock_wallet, ["t1"]) == 100

        mock_prisma_client.db.reviews.count = AsyncMock(return_value=7)
        assert await q.get_review_count_for_employee(mock_emp) == 7
        assert await q.get_reviews_this_month_for_employee(mock_emp) == 7

        mock_prisma_client.db.reward_history.count = AsyncMock(return_value=3)
        assert await q.get_rewards_redeemed_for_wallet(mock_wallet) == 3

    # ===========================================================================
    # LEGACY FUNCTIONS (Testing fallbacks)
    # ===========================================================================
    async def test_legacy_functions_no_wallet(self):
        mock_prisma_client.db.wallets.find_first = AsyncMock(return_value=None)
        
        assert await q.get_user_total_points("e1") == 0
        assert await q.get_user_points_earned_this_month("e1") == 0
        assert await q.get_user_points_earned_last_month("e1") == 0
        assert await q.get_user_total_rewards_redeemed("e1") == 0
        assert await q.get_user_rewards_redeemed_this_month("e1") == 0
        assert await q.get_user_rewards_redeemed_last_month("e1") == 0

    async def test_legacy_functions_with_wallet_no_credits(self):
        mock_wallet = MagicMock()
        mock_wallet.available_points = 500
        mock_prisma_client.db.wallets.find_first = AsyncMock(return_value=mock_wallet)
        mock_prisma_client.db.transaction_types.find_many = AsyncMock(return_value=[]) # No credits
        
        assert await q.get_user_total_points("e1") == 500
        assert await q.get_user_points_earned_this_month("e1") == 0
        assert await q.get_user_points_earned_last_month("e1") == 0

    async def test_legacy_reviews(self):
        mock_prisma_client.db.reviews.count = AsyncMock(return_value=12)
        assert await q.get_user_total_reviews("e1") == 12
        assert await q.get_user_reviews_this_month("e1") == 12
        assert await q.get_user_reviews_last_month("e1") == 12