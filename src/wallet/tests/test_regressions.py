"""
src/wallet/tests/test_regressions.py
──────────────────────────────────────
Regression tests guarding known bugs and edge cases in the wallet service.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.wallet.service as svc
from conftest import (
    _fake_wallet, _fake_txn_type, _fake_status, _fake_txn,
    _fake_review, _fake_category_tag, _current_user, make_uuid, utcnow,
)

_SVC = "src.wallet.service"


def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm(): yield
    return _cm()


def _noop_tx():
    @asynccontextmanager
    async def _ctx():
        tx = MagicMock()
        tx.transactions = MagicMock()
        tx.transactions.create = AsyncMock(return_value=MagicMock())
        tx.wallets = MagicMock()
        tx.wallets.update_many = AsyncMock(return_value=1)
        yield tx
    return _ctx()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: is_admin must check BOTH HR_ADMIN and SUPER_ADMIN
# ─────────────────────────────────────────────────────────────────────────────

class TestIsAdminRoleCheck:
    def test_hr_admin_allowed(self):
        assert svc.is_admin(_current_user(roles=["HR_ADMIN"])) is True

    def test_super_admin_allowed(self):
        assert svc.is_admin(_current_user(roles=["SUPER_ADMIN"])) is True

    def test_manager_not_allowed(self):
        assert svc.is_admin(_current_user(roles=["MANAGER"])) is False

    def test_employee_not_allowed(self):
        assert svc.is_admin(_current_user(roles=["EMPLOYEE"])) is False

    def test_combined_employee_hr_admin_is_admin(self):
        assert svc.is_admin(_current_user(roles=["EMPLOYEE", "HR_ADMIN"])) is True


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: credit_wallet_from_review — raw_points=None must raise 422
# (not silently award 0 or crash with AttributeError)
# ─────────────────────────────────────────────────────────────────────────────

class TestRawPointsNoneRaises422:
    async def test_none_raw_points_raises_422(self):
        review = _fake_review(raw_points=None); user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=review)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(str(review.review_id), user)
        assert exc.value.status_code == 422

    async def test_422_error_mentions_raw_points(self):
        review = _fake_review(raw_points=None); user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=review)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(str(review.review_id), user)
        assert "raw_points" in exc.value.detail


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: credit_wallet_from_review — points must be minimum 1
# (max(1, round(raw_points)) prevents awarding 0 for very small positive values)
# ─────────────────────────────────────────────────────────────────────────────

class TestMinimumOnePoint:
    async def test_raw_points_0_6_rounds_to_1(self):
        """round(0.6) = 1, then max(1, 1) = 1 — minimum of 1 point."""
        review   = _fake_review(raw_points=0.6); user = _current_user()
        wallet   = _fake_wallet(employee_id=str(review.receiver_id))
        txn_type = _fake_txn_type(); status = _fake_status(status_code="APPROVED")
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock),
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=txn_type)
            mock_sm.find_first  = AsyncMock(return_value=status)
            result = await svc.credit_wallet_from_review(str(review.review_id), user)
        assert result["credited_points"] >= 1

    async def test_very_small_raw_points_gets_min_1(self):
        """raw_points=0.1 rounds to 0, but max(1, 0) = 1 floors at 1."""
        review   = _fake_review(raw_points=0.1); user = _current_user()
        wallet   = _fake_wallet(employee_id=str(review.receiver_id))
        txn_type = _fake_txn_type(); status = _fake_status(status_code="APPROVED")
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock),
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=txn_type)
            mock_sm.find_first  = AsyncMock(return_value=status)
            result = await svc.credit_wallet_from_review(str(review.review_id), user)
        assert result["credited_points"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: adjust_wallet_for_review_update — delta that rounds to zero
# must NOT write a transaction (early return)
# ─────────────────────────────────────────────────────────────────────────────

class TestZeroDeltaEarlyReturn:
    async def test_delta_0_4_rounds_to_zero_returns_early(self):
        user = _current_user()
        # round(0.4) = 0 → should return immediately without DB calls
        with patch.object(svc.db, "reviews") as mock_r:
            result = await svc.adjust_wallet_for_review_update(make_uuid(), 0.4, user)
            mock_r.find_unique.assert_not_awaited()
        assert result["credited_points"] == 0

    async def test_delta_minus_0_4_rounds_to_zero_returns_early(self):
        user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            result = await svc.adjust_wallet_for_review_update(make_uuid(), -0.4, user)
            mock_r.find_unique.assert_not_awaited()
        assert result["credited_points"] == 0

    async def test_exactly_zero_returns_early(self):
        user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            result = await svc.adjust_wallet_for_review_update(make_uuid(), 0.0, user)
            mock_r.find_unique.assert_not_awaited()
        assert result["credited_points"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: adjust_wallet_for_review_update — debit must not take balance
# below zero (skip debit and return graceful message)
# ─────────────────────────────────────────────────────────────────────────────

class TestDebitNotBelowZero:
    async def test_debit_larger_than_balance_skips(self):
        review = _fake_review(); user = _current_user()
        wallet = _fake_wallet(available_points=3)  # only 3 pts
        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_r.find_unique = AsyncMock(return_value=review)
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.adjust_wallet_for_review_update(
                str(review.review_id), -10.0, user)
        assert "skipped" in result["message"].lower()
        assert result["new_balance"] == 3  # unchanged

    async def test_debit_exactly_equal_to_balance_proceeds(self):
        """delta=-5 when available=5 → 5-5=0, not negative, should proceed."""
        review   = _fake_review(); user = _current_user()
        wallet   = _fake_wallet(available_points=5)
        txn_type = _fake_txn_type(type_code="DEBIT"); status = _fake_status(status_code="APPROVED")
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock),
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=txn_type)
            mock_sm.find_first  = AsyncMock(return_value=status)
            result = await svc.adjust_wallet_for_review_update(
                str(review.review_id), -5.0, user)
        assert result["credited_points"] == -5
        assert result["new_balance"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: employee_consumer idempotency — same employee_id twice
# must only create one wallet
# ─────────────────────────────────────────────────────────────────────────────

class TestEmployeeConsumerIdempotency:
    async def test_second_call_skips_create(self):
        from src.wallet.employee_consumer import _provision_wallet
        existing = _fake_wallet()
        with patch("src.wallet.employee_consumer.db") as mock_db:
            mock_db.wallets.find_first = AsyncMock(return_value=existing)
            await _provision_wallet(make_uuid(), "admin")
            await _provision_wallet(make_uuid(), "admin")
        mock_db.wallets.create.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: review_consumer idempotency — same review_id twice
# must only create one transaction
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewConsumerIdempotency:
    async def test_existing_transaction_skips_credit(self):
        from src.wallet.review_consumer import _credit_points
        existing = _fake_txn(reference_number="review-123")
        with patch("src.wallet.review_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=existing)
            await _credit_points("review-123", make_uuid(), 10)
        mock_db.wallets.find_first.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: reward_consumer idempotency — same redemption_id twice
# must only deduct once
# ─────────────────────────────────────────────────────────────────────────────

class TestRewardConsumerIdempotency:
    async def test_existing_transaction_skips_deduction(self):
        from src.wallet.reward_consumer import _deduct_points
        existing = _fake_txn(reference_number="redemption:hist-1")
        with patch("src.wallet.reward_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=existing)
            await _deduct_points("hist-1", make_uuid(), 50, "user-1")
        mock_db.wallets.find_first.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: wallet_key format must match what reward_consumer invalidates
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheKeyConsistency:
    def test_wallet_key_format(self):
        eid = make_uuid()
        assert svc._wallet_key(eid) == f"wallets:employee:{eid}"

    def test_txn_types_cache_key(self):
        assert svc._KEY_TXN_TYPES == "wallet:transaction_types"
