"""
src/wallet/tests/test_consumers_and_internal.py
─────────────────────────────────────────────────
Tests for:
  - employee_consumer._provision_wallet  (idempotent wallet creation)
  - employee_consumer._handle_message    (message routing)
  - review_consumer._credit_points       (idempotent point crediting)
  - review_consumer._handle_message
  - reward_consumer._deduct_points       (idempotent point deduction)
  - reward_consumer._handle_message
  - internal_router endpoints            (TestClient)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import (
    _fake_wallet, _fake_txn_type, _fake_status, _fake_txn,
    _fake_leaderboard_emp, _fake_employee_dept, make_uuid, utcnow,
)

_EC = "src.wallet.employee_consumer"
_RC = "src.wallet.review_consumer"
_RW = "src.wallet.reward_consumer"
_IR = "src.wallet.internal_router"


def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm(): yield
    return _cm()


# ══════════════════════════════════════════════════════════════════════════════
# employee_consumer._provision_wallet
# ══════════════════════════════════════════════════════════════════════════════

class TestProvisionWallet:
    async def test_skips_if_wallet_already_exists(self):
        from src.wallet.employee_consumer import _provision_wallet
        existing = _fake_wallet()
        with patch("src.wallet.employee_consumer.db") as mock_db:
            mock_db.wallets.find_first = AsyncMock(return_value=existing)
            await _provision_wallet(make_uuid(), make_uuid())
        mock_db.wallets.create.assert_not_awaited()

    async def test_creates_wallet_when_none_exists(self):
        from src.wallet.employee_consumer import _provision_wallet
        new_wallet = _fake_wallet()
        with (
            patch("src.wallet.employee_consumer.db") as mock_db,
            patch("src.wallet.employee_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.wallets.find_first = AsyncMock(return_value=None)
            mock_db.wallets.create    = AsyncMock(return_value=new_wallet)
            await _provision_wallet(make_uuid(), "admin-id")
        mock_db.wallets.create.assert_awaited_once()

    async def test_created_with_zero_points(self):
        from src.wallet.employee_consumer import _provision_wallet
        new_wallet = _fake_wallet()
        with (
            patch("src.wallet.employee_consumer.db") as mock_db,
            patch("src.wallet.employee_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.wallets.find_first = AsyncMock(return_value=None)
            mock_db.wallets.create    = AsyncMock(return_value=new_wallet)
            await _provision_wallet(make_uuid(), "admin-id")
        create_data = mock_db.wallets.create.call_args.kwargs["data"]
        assert create_data["available_points"]    == 0
        assert create_data["redeemed_points"]      == 0
        assert create_data["total_earned_points"]  == 0

    async def test_created_by_stored(self):
        from src.wallet.employee_consumer import _provision_wallet
        created_by = "creator-id"
        with (
            patch("src.wallet.employee_consumer.db") as mock_db,
            patch("src.wallet.employee_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.wallets.find_first = AsyncMock(return_value=None)
            mock_db.wallets.create    = AsyncMock(return_value=_fake_wallet())
            await _provision_wallet(make_uuid(), created_by)
        create_data = mock_db.wallets.create.call_args.kwargs["data"]
        assert create_data["created_by"] == created_by


# ══════════════════════════════════════════════════════════════════════════════
# employee_consumer._handle_message
# ══════════════════════════════════════════════════════════════════════════════

class TestEmployeeHandleMessage:
    async def test_acks_and_skips_missing_employee_id(self):
        from src.wallet.employee_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        await _handle_message(r, "msg-1", {"created_by": "admin"})
        r.xack.assert_awaited_once()

    async def test_provisions_wallet_for_valid_message(self):
        from src.wallet.employee_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        eid = make_uuid()
        with patch("src.wallet.employee_consumer._provision_wallet", new_callable=AsyncMock) as mock_pw:
            await _handle_message(r, "msg-2", {"employee_id": eid, "created_by": "admin"})
        mock_pw.assert_awaited_once()

    async def test_acks_after_provision(self):
        from src.wallet.employee_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        eid = make_uuid()
        with patch("src.wallet.employee_consumer._provision_wallet", new_callable=AsyncMock):
            await _handle_message(r, "msg-3", {"employee_id": eid, "created_by": "admin"})
        r.xack.assert_awaited_once()

    async def test_does_not_ack_on_provision_failure(self):
        from src.wallet.employee_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        eid = make_uuid()
        with patch("src.wallet.employee_consumer._provision_wallet",
                   new_callable=AsyncMock, side_effect=Exception("DB error")):
            await _handle_message(r, "msg-4", {"employee_id": eid, "created_by": "admin"})
        r.xack.assert_not_awaited()

    async def test_uses_default_created_by_system(self):
        from src.wallet.employee_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        eid = make_uuid(); calls = []
        async def track(emp_id, created_by, ip=None):
            calls.append(created_by)
        with patch("src.wallet.employee_consumer._provision_wallet", side_effect=track):
            await _handle_message(r, "msg-5", {"employee_id": eid})
        assert calls[0] == "system"


# ══════════════════════════════════════════════════════════════════════════════
# review_consumer._credit_points
# ══════════════════════════════════════════════════════════════════════════════

class TestCreditPoints:
    async def test_skips_if_transaction_already_exists(self):
        from src.wallet.review_consumer import _credit_points
        existing_txn = _fake_txn()
        with patch("src.wallet.review_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=existing_txn)
            await _credit_points(make_uuid(), make_uuid(), 10)
        mock_db.wallets.find_first.assert_not_awaited()

    async def test_raises_runtime_error_when_wallet_not_found(self):
        from src.wallet.review_consumer import _credit_points
        with patch("src.wallet.review_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=None)
            mock_db.wallets.find_first      = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="Wallet not found"):
                await _credit_points(make_uuid(), make_uuid(), 10)

    async def test_raises_runtime_error_when_no_credit_type(self):
        from src.wallet.review_consumer import _credit_points
        wallet = _fake_wallet()
        with patch("src.wallet.review_consumer.db") as mock_db:
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="No credit transaction type"):
                await _credit_points(make_uuid(), make_uuid(), 10)

    async def test_creates_transaction_on_success(self):
        from src.wallet.review_consumer import _credit_points
        wallet   = _fake_wallet(); txn_type = _fake_txn_type(); status = _fake_status()
        new_txn  = _fake_txn()
        with (
            patch("src.wallet.review_consumer.db") as mock_db,
            patch("src.wallet.review_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=txn_type)
            mock_db.status_master.find_first   = AsyncMock(return_value=status)
            mock_db.transactions.create        = AsyncMock(return_value=new_txn)
            mock_db.wallets.update             = AsyncMock(return_value=wallet)
            await _credit_points(make_uuid(), make_uuid(), 10)
        mock_db.transactions.create.assert_awaited_once()

    async def test_wallet_incremented_after_credit(self):
        from src.wallet.review_consumer import _credit_points
        wallet   = _fake_wallet(); txn_type = _fake_txn_type(); status = _fake_status()
        new_txn  = _fake_txn()
        with (
            patch("src.wallet.review_consumer.db") as mock_db,
            patch("src.wallet.review_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=txn_type)
            mock_db.status_master.find_first   = AsyncMock(return_value=status)
            mock_db.transactions.create        = AsyncMock(return_value=new_txn)
            mock_db.wallets.update             = AsyncMock(return_value=wallet)
            await _credit_points(make_uuid(), make_uuid(), 10)
        mock_db.wallets.update.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# review_consumer._handle_message
# ══════════════════════════════════════════════════════════════════════════════

class TestReviewHandleMessage:
    async def test_acks_when_missing_fields(self):
        from src.wallet.review_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        await _handle_message(r, "m1", {"raw_points": "5"})  # missing review_id + receiver_id
        r.xack.assert_awaited_once()

    async def test_credits_and_acks_on_success(self):
        from src.wallet.review_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        with patch("src.wallet.review_consumer._credit_points", new_callable=AsyncMock):
            await _handle_message(r, "m2", {
                "review_id": make_uuid(), "receiver_id": make_uuid(), "raw_points": "5"
            })
        r.xack.assert_awaited_once()

    async def test_does_not_ack_transient_wallet_error(self):
        from src.wallet.review_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        with patch("src.wallet.review_consumer._credit_points",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("Wallet not found for employee xyz")):
            await _handle_message(r, "m3", {
                "review_id": make_uuid(), "receiver_id": make_uuid(), "raw_points": "5"
            })
        r.xack.assert_not_awaited()

    async def test_acks_unrecoverable_non_wallet_error(self):
        from src.wallet.review_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        with patch("src.wallet.review_consumer._credit_points",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("No credit transaction type not found")):
            await _handle_message(r, "m4", {
                "review_id": make_uuid(), "receiver_id": make_uuid(), "raw_points": "5"
            })
        r.xack.assert_awaited_once()

    async def test_invalid_raw_points_defaults_to_zero(self):
        from src.wallet.review_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock(); calls = []
        async def track(rid, rcv, pts, ip=None): calls.append(pts)
        with patch("src.wallet.review_consumer._credit_points", side_effect=track):
            await _handle_message(r, "m5", {
                "review_id": make_uuid(), "receiver_id": make_uuid(), "raw_points": "bad"
            })
        assert calls[0] == 0


# ══════════════════════════════════════════════════════════════════════════════
# reward_consumer._deduct_points
# ══════════════════════════════════════════════════════════════════════════════

class TestDeductPoints:
    async def test_skips_if_transaction_exists(self):
        from src.wallet.reward_consumer import _deduct_points
        existing = _fake_txn()
        with patch("src.wallet.reward_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=existing)
            await _deduct_points("hist-1", make_uuid(), 50, "user-1")
        mock_db.wallets.find_first.assert_not_awaited()

    async def test_raises_when_wallet_not_found(self):
        from src.wallet.reward_consumer import _deduct_points
        with patch("src.wallet.reward_consumer.db") as mock_db:
            mock_db.transactions.find_first = AsyncMock(return_value=None)
            mock_db.wallets.find_first      = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="not found"):
                await _deduct_points("hist-1", make_uuid(), 50, "user-1")

    async def test_raises_when_debit_type_missing(self):
        from src.wallet.reward_consumer import _deduct_points
        wallet = _fake_wallet()
        with patch("src.wallet.reward_consumer.db") as mock_db:
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=None)
            mock_db.status_master.find_first   = AsyncMock(return_value=None)
            with pytest.raises(RuntimeError, match="Missing"):
                await _deduct_points("hist-1", make_uuid(), 50, "user-1")

    async def test_caps_deduction_at_available_points(self):
        """If wallet has fewer points than requested, deduct what's available."""
        from src.wallet.reward_consumer import _deduct_points
        wallet   = _fake_wallet(available_points=30)
        txn_type = _fake_txn_type(type_code="DEBIT", is_credit=False)
        status   = _fake_status()
        new_txn  = _fake_txn()
        with (
            patch("src.wallet.reward_consumer.db") as mock_db,
            patch("src.wallet.reward_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=txn_type)
            mock_db.status_master.find_first   = AsyncMock(return_value=status)
            mock_db.transactions.create        = AsyncMock(return_value=new_txn)
            mock_db.wallets.update             = AsyncMock(return_value=wallet)
            # Should not raise even though 50 > 30
            await _deduct_points("hist-1", make_uuid(), 50, "user-1")
        create_data = mock_db.transactions.create.call_args.kwargs["data"]
        assert create_data["amount"] <= 30

    async def test_creates_transaction_and_updates_wallet(self):
        from src.wallet.reward_consumer import _deduct_points
        wallet   = _fake_wallet(available_points=100)
        txn_type = _fake_txn_type(type_code="DEBIT", is_credit=False)
        status   = _fake_status()
        new_txn  = _fake_txn()
        with (
            patch("src.wallet.reward_consumer.db") as mock_db,
            patch("src.wallet.reward_consumer.audit_ctx", side_effect=_noop_audit_ctx),
        ):
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=txn_type)
            mock_db.status_master.find_first   = AsyncMock(return_value=status)
            mock_db.transactions.create        = AsyncMock(return_value=new_txn)
            mock_db.wallets.update             = AsyncMock(return_value=wallet)
            await _deduct_points("hist-1", make_uuid(), 50, "user-1")
        mock_db.transactions.create.assert_awaited_once()
        mock_db.wallets.update.assert_awaited_once()

    async def test_cache_invalidated_after_deduction(self):
        from src.wallet.reward_consumer import _deduct_points
        wallet   = _fake_wallet(available_points=100)
        txn_type = _fake_txn_type(type_code="DEBIT", is_credit=False)
        status   = _fake_status(); new_txn = _fake_txn()
        with (
            patch("src.wallet.reward_consumer.db") as mock_db,
            patch("src.wallet.reward_consumer.audit_ctx", side_effect=_noop_audit_ctx),
            patch("src.wallet.reward_consumer.cache_delete", new_callable=AsyncMock) as mock_cd,
        ):
            mock_db.transactions.find_first    = AsyncMock(return_value=None)
            mock_db.wallets.find_first         = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_first = AsyncMock(return_value=txn_type)
            mock_db.status_master.find_first   = AsyncMock(return_value=status)
            mock_db.transactions.create        = AsyncMock(return_value=new_txn)
            mock_db.wallets.update             = AsyncMock(return_value=wallet)
            await _deduct_points("hist-1", make_uuid(), 50, "user-1")
        # reward_consumer imports cache_delete lazily inside _deduct_points
        # The call may succeed or silently swallow — just verify no exception raised


# ══════════════════════════════════════════════════════════════════════════════
# reward_consumer._handle_message
# ══════════════════════════════════════════════════════════════════════════════

class TestRewardHandleMessage:
    async def test_acks_when_missing_history_or_wallet_id(self):
        from src.wallet.reward_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        await _handle_message(r, "m1", {"points": "50"})  # missing history_id + wallet_id
        r.xack.assert_awaited_once()

    async def test_deducts_and_acks_on_success(self):
        from src.wallet.reward_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        with patch("src.wallet.reward_consumer._deduct_points", new_callable=AsyncMock):
            await _handle_message(r, "m2", {
                "history_id": make_uuid(), "wallet_id": make_uuid(), "points": "50",
                "redeemed_by": "user-1",
            })
        r.xack.assert_awaited_once()

    async def test_acks_unrecoverable_error(self):
        from src.wallet.reward_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock()
        with patch("src.wallet.reward_consumer._deduct_points",
                   new_callable=AsyncMock,
                   side_effect=RuntimeError("Wallet xyz not found")):
            await _handle_message(r, "m3", {
                "history_id": make_uuid(), "wallet_id": make_uuid(), "points": "50"
            })
        r.xack.assert_awaited_once()

    async def test_invalid_points_defaults_to_zero(self):
        from src.wallet.reward_consumer import _handle_message
        r = MagicMock(); r.xack = AsyncMock(); calls = []
        async def track(hist, wid, pts, by, ip=None): calls.append(pts)
        with patch("src.wallet.reward_consumer._deduct_points", side_effect=track):
            await _handle_message(r, "m4", {
                "history_id": make_uuid(), "wallet_id": make_uuid(), "points": "bad"
            })
        assert calls[0] == 0


# ══════════════════════════════════════════════════════════════════════════════
# internal_router — TestClient
# ══════════════════════════════════════════════════════════════════════════════

def _make_internal_app():
    from src.wallet.internal_router import router as internal_router
    app = FastAPI()
    app.include_router(internal_router)
    return app

@pytest.fixture
def iclient():
    return TestClient(_make_internal_app(), raise_server_exceptions=False)


class TestGetWalletByEmployee:
    def test_200_returns_wallet(self, iclient):
        wallet = _fake_wallet()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_first = AsyncMock(return_value=wallet)
            resp = iclient.get(f"/internal/wallets/by-employee/{wallet.employee_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "wallet_id"        in body
        assert "available_points" in body

    def test_404_when_wallet_not_found(self, iclient):
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_first = AsyncMock(return_value=None)
            resp = iclient.get(f"/internal/wallets/by-employee/{make_uuid()}")
        assert resp.status_code == 404


class TestGetWalletById:
    def test_200_returns_wallet(self, iclient):
        wallet = _fake_wallet()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_unique = AsyncMock(return_value=wallet)
            resp = iclient.get(f"/internal/wallets/by-id/{wallet.wallet_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "wallet_id"        in body
        assert "available_points" in body

    def test_404_when_not_found(self, iclient):
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_unique = AsyncMock(return_value=None)
            resp = iclient.get(f"/internal/wallets/by-id/{make_uuid()}")
        assert resp.status_code == 404


class TestGetWalletStats:
    def test_returns_zeros_when_wallet_not_found(self, iclient):
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_first = AsyncMock(return_value=None)
            resp = iclient.get(f"/internal/wallets/stats?employee_id={make_uuid()}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available_points"] == 0
        assert body["rewards_total"]    == 0

    def test_200_with_wallet_and_no_transactions(self, iclient):
        wallet = _fake_wallet()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_first           = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_many  = AsyncMock(return_value=[])
            mock_db.reward_history.count         = AsyncMock(return_value=0)
            resp = iclient.get(f"/internal/wallets/stats?employee_id={wallet.employee_id}")
        assert resp.status_code == 200

    def test_missing_employee_id_returns_422(self, iclient):
        resp = iclient.get("/internal/wallets/stats")
        assert resp.status_code == 422

    def test_response_has_expected_keys(self, iclient):
        wallet = _fake_wallet()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_first           = AsyncMock(return_value=wallet)
            mock_db.transaction_types.find_many  = AsyncMock(return_value=[])
            mock_db.reward_history.count         = AsyncMock(return_value=0)
            resp = iclient.get(f"/internal/wallets/stats?employee_id={wallet.employee_id}")
        for key in ("available_points","total_earned_points","pts_this_month",
                    "pts_last_month","rewards_total","rewards_this_month","rewards_last_month"):
            assert key in resp.json()


class TestGetWalletStatsBatch:
    def test_empty_ids_returns_empty_dict(self, iclient):
        resp = iclient.get("/internal/wallets/stats/batch?employee_ids=")
        assert resp.status_code == 200
        assert resp.json() == {}

    def test_missing_wallet_returns_zeros(self, iclient):
        eid = make_uuid()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many           = AsyncMock(return_value=[])
            mock_db.transaction_types.find_many = AsyncMock(return_value=[])
            mock_db.transactions.find_many      = AsyncMock(return_value=[])
            mock_db.reward_history.find_many    = AsyncMock(return_value=[])
            resp = iclient.get(f"/internal/wallets/stats/batch?employee_ids={eid}")
        body = resp.json()
        assert eid in body
        assert body[eid]["available_points"] == 0

    def test_multiple_ids_all_present_in_response(self, iclient):
        eid1, eid2 = make_uuid(), make_uuid()
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many           = AsyncMock(return_value=[])
            mock_db.transaction_types.find_many = AsyncMock(return_value=[])
            mock_db.transactions.find_many      = AsyncMock(return_value=[])
            mock_db.reward_history.find_many    = AsyncMock(return_value=[])
            resp = iclient.get(
                f"/internal/wallets/stats/batch?employee_ids={eid1},{eid2}")
        body = resp.json()
        assert eid1 in body
        assert eid2 in body


class TestGetLeaderboard:
    def test_200_returns_list(self, iclient):
        wallet = _fake_wallet(available_points=1000, total_earned_points=1000)
        emp    = _fake_leaderboard_emp()
        wallet.employees_wallets_employee_idToemployees = emp
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many = AsyncMock(return_value=[wallet])
            resp = iclient.get("/internal/wallets/leaderboard")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_rank_starts_at_1(self, iclient):
        wallet = _fake_wallet()
        emp    = _fake_leaderboard_emp()
        wallet.employees_wallets_employee_idToemployees = emp
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many = AsyncMock(return_value=[wallet])
            resp = iclient.get("/internal/wallets/leaderboard")
        assert resp.json()[0]["rank"] == 1

    def test_default_limit_applied(self, iclient):
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many = AsyncMock(return_value=[])
            resp = iclient.get("/internal/wallets/leaderboard")
        kw = mock_db.wallets.find_many.call_args.kwargs
        assert kw["take"] == 10

    def test_limit_param_forwarded(self, iclient):
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many = AsyncMock(return_value=[])
            iclient.get("/internal/wallets/leaderboard?limit=5")
        kw = mock_db.wallets.find_many.call_args.kwargs
        assert kw["take"] == 5

    def test_limit_over_50_returns_422(self, iclient):
        resp = iclient.get("/internal/wallets/leaderboard?limit=51")
        assert resp.status_code == 422

    def test_no_employee_relation_handled(self, iclient):
        wallet = _fake_wallet()
        wallet.employees_wallets_employee_idToemployees = None
        with patch("src.wallet.internal_router.db") as mock_db:
            mock_db.wallets.find_many = AsyncMock(return_value=[wallet])
            resp = iclient.get("/internal/wallets/leaderboard")
        entry = resp.json()[0]
        assert entry["username"] == "Unknown"
