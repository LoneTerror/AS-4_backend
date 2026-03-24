"""
src/wallet/tests/test_service.py
──────────────────────────────────
Unit tests for src/wallet/service.py.
All DB, cache, and notification calls are patched.
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


# ══════════════════════════════════════════════════════════════════════════════
# Helper constants
# ══════════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_wallet_not_found_message(self):
        assert svc.WNF == "Wallet not found"

    def test_access_denied_message(self):
        assert svc.AD == "Access Denied"

    def test_key_txn_types(self):
        assert svc._KEY_TXN_TYPES == "wallet:transaction_types"

    def test_wallet_key_includes_employee_id(self):
        eid = make_uuid()
        assert svc._wallet_key(eid) == f"wallets:employee:{eid}"


# ══════════════════════════════════════════════════════════════════════════════
# is_admin
# ══════════════════════════════════════════════════════════════════════════════

class TestIsAdmin:
    def test_hr_admin_is_admin(self):
        u = _current_user(roles=["HR_ADMIN"])
        assert svc.is_admin(u) is True

    def test_super_admin_is_admin(self):
        u = _current_user(roles=["SUPER_ADMIN"])
        assert svc.is_admin(u) is True

    def test_employee_is_not_admin(self):
        u = _current_user(roles=["EMPLOYEE"])
        assert svc.is_admin(u) is False

    def test_manager_is_not_admin(self):
        u = _current_user(roles=["MANAGER"])
        assert svc.is_admin(u) is False

    def test_empty_roles_is_not_admin(self):
        u = _current_user(roles=[])
        assert svc.is_admin(u) is False

    def test_multiple_roles_one_admin(self):
        u = _current_user(roles=["EMPLOYEE", "HR_ADMIN"])
        assert svc.is_admin(u) is True


# ══════════════════════════════════════════════════════════════════════════════
# get_transaction_types
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTransactionTypes:
    async def test_returns_list_from_db(self):
        types = [_fake_txn_type("CREDIT"), _fake_txn_type("DEBIT", is_credit=False)]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            mock_tt.find_many = AsyncMock(return_value=types)
            result = await svc.get_transaction_types(_current_user())
        assert len(result) == 2

    async def test_cache_hit_skips_db(self):
        cached = [{"type_id": make_uuid(), "code": "CREDIT", "name": "Credit", "is_credit": True}]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=cached),
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            result = await svc.get_transaction_types(_current_user())
            mock_tt.find_many.assert_not_awaited()
        assert result == cached

    async def test_cache_set_after_db(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock) as mock_cs,
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            mock_tt.find_many = AsyncMock(return_value=[])
            await svc.get_transaction_types(_current_user())
        mock_cs.assert_awaited_once()

    async def test_result_has_expected_keys(self):
        types = [_fake_txn_type()]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            mock_tt.find_many = AsyncMock(return_value=types)
            result = await svc.get_transaction_types(_current_user())
        item = result[0]
        for key in ("type_id", "code", "name", "is_credit"):
            assert key in item

    async def test_is_credit_flag_preserved(self):
        types = [_fake_txn_type(is_credit=False)]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            mock_tt.find_many = AsyncMock(return_value=types)
            result = await svc.get_transaction_types(_current_user())
        assert result[0]["is_credit"] is False


# ══════════════════════════════════════════════════════════════════════════════
# create_transaction
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateTransaction:
    def _data(self, **ov):
        from src.wallet.schemas import TransactionCreate
        import uuid
        base = dict(
            wallet_id=uuid.uuid4(), amount=100,
            transaction_type_id=uuid.uuid4(), reference_number="REF-001",
        )
        base.update(ov); return TransactionCreate(**base)

    def _wire_happy(self, mock_w, mock_tt, mock_sm, wallet=None, txn_type=None, status=None):
        mock_w.find_unique  = AsyncMock(return_value=wallet  or _fake_wallet())
        mock_tt.find_unique = AsyncMock(return_value=txn_type or _fake_txn_type())
        mock_sm.find_first  = AsyncMock(return_value=status  or _fake_status(status_code="APPROVED"))

    async def test_raises_403_for_non_admin(self):
        data = self._data(); user = _current_user(roles=["EMPLOYEE"])
        with pytest.raises(HTTPException) as exc:
            await svc.create_transaction(data, user)
        assert exc.value.status_code == 403

    async def test_raises_400_for_zero_amount(self):
        data = self._data(amount=0); user = _current_user(roles=["HR_ADMIN"])
        with pytest.raises(HTTPException) as exc:
            await svc.create_transaction(data, user)
        assert exc.value.status_code == 400

    async def test_raises_400_for_negative_amount(self):
        data = self._data(amount=-5); user = _current_user(roles=["HR_ADMIN"])
        with pytest.raises(HTTPException) as exc:
            await svc.create_transaction(data, user)
        assert exc.value.status_code == 400

    async def test_raises_404_when_wallet_not_found(self):
        data = self._data(); user = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.create_transaction(data, user)
        assert exc.value.status_code == 404

    async def test_raises_404_when_txn_type_not_found(self):
        data = self._data(); user = _current_user()
        with (
            patch.object(svc.db, "wallets")            as mock_w,
            patch.object(svc.db, "transaction_types")  as mock_tt,
        ):
            mock_w.find_unique  = AsyncMock(return_value=_fake_wallet())
            mock_tt.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.create_transaction(data, user)
        assert exc.value.status_code == 404

    async def test_raises_500_when_approved_status_missing(self):
        data = self._data(); user = _current_user()
        with (
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
        ):
            self._wire_happy(mock_w, mock_tt, mock_sm, status=None)
            mock_sm.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.create_transaction(data, user)
        assert exc.value.status_code == 500

    async def test_raises_400_for_insufficient_balance_on_debit(self):
        wallet   = _fake_wallet(available_points=50)
        txn_type = _fake_txn_type(type_code="DEBIT", is_credit=False)
        data     = self._data(amount=100); user = _current_user()
        with (
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
        ):
            self._wire_happy(mock_w, mock_tt, mock_sm, wallet=wallet, txn_type=txn_type)
            with pytest.raises(HTTPException) as exc:
                await svc.create_transaction(data, user)
        assert exc.value.status_code == 400
        assert "insufficient" in exc.value.detail.lower()

    async def test_successful_credit_transaction(self):
        wallet   = _fake_wallet(available_points=200)
        txn_type = _fake_txn_type(type_code="CREDIT", is_credit=True)
        new_txn  = _fake_txn()
        data     = self._data(amount=50); user = _current_user()
        with (
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch.object(svc.db, "transactions")      as mock_t,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock),
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            self._wire_happy(mock_w, mock_tt, mock_sm, wallet=wallet, txn_type=txn_type)
            mock_t.find_unique = AsyncMock(return_value=new_txn)
            result = await svc.create_transaction(data, user)
        assert result is new_txn

    async def test_cache_invalidated_after_successful_txn(self):
        wallet   = _fake_wallet(); txn_type = _fake_txn_type(); new_txn = _fake_txn()
        data     = self._data(); user = _current_user()
        with (
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch.object(svc.db, "transactions")      as mock_t,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd,
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            self._wire_happy(mock_w, mock_tt, mock_sm, wallet=wallet, txn_type=txn_type)
            mock_t.find_unique = AsyncMock(return_value=new_txn)
            await svc.create_transaction(data, user)
        mock_cd.assert_awaited()

    async def test_notification_sent_after_txn(self):
        wallet   = _fake_wallet(); txn_type = _fake_txn_type(); new_txn = _fake_txn()
        data     = self._data(); user = _current_user()
        notif_svc = MagicMock(); notif_svc.create_notification = AsyncMock()
        with (
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch.object(svc.db, "transactions")      as mock_t,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock),
            patch(f"{_SVC}._get_notif", return_value=notif_svc),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            self._wire_happy(mock_w, mock_tt, mock_sm, wallet=wallet, txn_type=txn_type)
            mock_t.find_unique = AsyncMock(return_value=new_txn)
            await svc.create_transaction(data, user)
        notif_svc.create_notification.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# get_transactions
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTransactions:
    async def test_raises_404_when_wallet_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_transactions(make_uuid(), 1, 10, user)
        assert exc.value.status_code == 404

    async def test_raises_403_when_non_admin_accesses_other_wallet(self):
        wallet = _fake_wallet(employee_id="owner-id")
        user   = _current_user(user_id="other-id", roles=["EMPLOYEE"])
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=wallet)
            with pytest.raises(HTTPException) as exc:
                await svc.get_transactions(str(wallet.wallet_id), 1, 10, user)
        assert exc.value.status_code == 403

    async def test_admin_can_access_any_wallet(self):
        wallet = _fake_wallet(employee_id="owner-id")
        user   = _current_user(user_id="admin-id", roles=["HR_ADMIN"])
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(return_value=[])
            mock_t.count       = AsyncMock(return_value=0)
            result = await svc.get_transactions(str(wallet.wallet_id), 1, 10, user)
        assert "transactions" in result

    async def test_owner_can_access_own_wallet(self):
        eid    = make_uuid()
        wallet = _fake_wallet(employee_id=eid)
        user   = _current_user(user_id=eid, roles=["EMPLOYEE"])
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(return_value=[])
            mock_t.count       = AsyncMock(return_value=0)
            result = await svc.get_transactions(str(wallet.wallet_id), 1, 10, user)
        assert result["total"] == 0

    async def test_pagination_fields_in_response(self):
        wallet = _fake_wallet()
        user   = _current_user()
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(return_value=[])
            mock_t.count       = AsyncMock(return_value=0)
            result = await svc.get_transactions(str(wallet.wallet_id), 2, 5, user)
        assert result["page"] == 2
        assert result["limit"] == 5

    async def test_skip_offset_applied(self):
        wallet = _fake_wallet(); user = _current_user()
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(return_value=[])
            mock_t.count       = AsyncMock(return_value=0)
            await svc.get_transactions(str(wallet.wallet_id), 3, 10, user)
        kw = mock_t.find_many.call_args.kwargs
        assert kw["skip"] == 20

    async def test_status_code_filter_applied(self):
        wallet = _fake_wallet(); user = _current_user()
        stat   = _fake_status(status_code="SUCCESS")
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "status_master") as mock_sm,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_sm.find_unique = AsyncMock(return_value=stat)
            mock_t.find_many    = AsyncMock(return_value=[])
            mock_t.count        = AsyncMock(return_value=0)
            await svc.get_transactions(str(wallet.wallet_id), 1, 10, user, status_code="SUCCESS")
        kw = mock_t.find_many.call_args.kwargs
        assert "status_id" in kw["where"]


# ══════════════════════════════════════════════════════════════════════════════
# get_transaction_by_id
# ══════════════════════════════════════════════════════════════════════════════

class TestGetTransactionById:
    async def test_raises_404_when_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "transactions") as mock_t:
            mock_t.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_transaction_by_id(make_uuid(), user)
        assert exc.value.status_code == 404

    async def test_raises_403_non_admin_other_wallet(self):
        txn    = _fake_txn(wallet_id="wallet-x")
        wallet = _fake_wallet(wallet_id="wallet-x", employee_id="owner-id")
        user   = _current_user(user_id="other-id", roles=["EMPLOYEE"])
        with (
            patch.object(svc.db, "transactions") as mock_t,
            patch.object(svc.db, "wallets")      as mock_w,
        ):
            mock_t.find_unique = AsyncMock(return_value=txn)
            mock_w.find_unique = AsyncMock(return_value=wallet)
            with pytest.raises(HTTPException) as exc:
                await svc.get_transaction_by_id(str(txn.transaction_id), user)
        assert exc.value.status_code == 403

    async def test_admin_can_access_any_txn(self):
        txn  = _fake_txn(); user = _current_user(roles=["HR_ADMIN"])
        with patch.object(svc.db, "transactions") as mock_t:
            mock_t.find_unique = AsyncMock(return_value=txn)
            result = await svc.get_transaction_by_id(str(txn.transaction_id), user)
        assert "transaction_id" in result

    async def test_returns_expected_keys(self):
        txn  = _fake_txn(); user = _current_user()
        with patch.object(svc.db, "transactions") as mock_t:
            mock_t.find_unique = AsyncMock(return_value=txn)
            result = await svc.get_transaction_by_id(str(txn.transaction_id), user)
        for key in ("transaction_id","wallet_id","amount","status","transaction_type"):
            assert key in result


# ══════════════════════════════════════════════════════════════════════════════
# get_wallet_by_employee
# ══════════════════════════════════════════════════════════════════════════════

class TestGetWalletByEmployee:
    async def test_raises_403_non_admin_other_employee(self):
        user = _current_user(user_id="me", roles=["EMPLOYEE"])
        with pytest.raises(HTTPException) as exc:
            await svc.get_wallet_by_employee("other-employee", user)
        assert exc.value.status_code == 403

    async def test_raises_404_when_wallet_not_found(self):
        eid  = make_uuid()
        user = _current_user(user_id=eid, roles=["EMPLOYEE"])
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_wallet_by_employee(eid, user)
        assert exc.value.status_code == 404

    async def test_returns_wallet(self):
        eid    = make_uuid()
        wallet = _fake_wallet(employee_id=eid)
        user   = _current_user(user_id=eid, roles=["EMPLOYEE"])
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.get_wallet_by_employee(eid, user)
        assert result is wallet

    async def test_cache_hit_returns_cached(self):
        eid    = make_uuid()
        cached = {"wallet_id": make_uuid(), "employee_id": eid}
        user   = _current_user(user_id=eid)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=cached),
            patch.object(svc.db, "wallets") as mock_w,
        ):
            result = await svc.get_wallet_by_employee(eid, user)
            mock_w.find_unique.assert_not_awaited()
        assert result == cached

    async def test_admin_can_access_any_employee(self):
        eid    = make_uuid()
        wallet = _fake_wallet(employee_id=eid)
        user   = _current_user(user_id="admin-id", roles=["HR_ADMIN"])
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.get_wallet_by_employee(eid, user)
        assert result is wallet

    async def test_cache_set_after_db_fetch(self):
        eid    = make_uuid()
        wallet = _fake_wallet(employee_id=eid)
        user   = _current_user(user_id=eid)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock) as mock_cs,
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            await svc.get_wallet_by_employee(eid, user)
        mock_cs.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# get_wallet_balance
# ══════════════════════════════════════════════════════════════════════════════

class TestGetWalletBalance:
    async def test_raises_404_when_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_wallet_balance(make_uuid(), user)
        assert exc.value.status_code == 404

    async def test_raises_403_non_admin_other_wallet(self):
        wallet = _fake_wallet(employee_id="owner")
        user   = _current_user(user_id="other", roles=["EMPLOYEE"])
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=wallet)
            with pytest.raises(HTTPException) as exc:
                await svc.get_wallet_balance(str(wallet.wallet_id), user)
        assert exc.value.status_code == 403

    async def test_returns_balance_dict(self):
        wallet = _fake_wallet(available_points=350)
        user   = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.get_wallet_balance(str(wallet.wallet_id), user)
        assert result["available_points"] == 350

    async def test_response_has_wallet_id(self):
        wallet = _fake_wallet(); user = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.get_wallet_balance(str(wallet.wallet_id), user)
        assert "wallet_id" in result


# ══════════════════════════════════════════════════════════════════════════════
# get_points_summary
# ══════════════════════════════════════════════════════════════════════════════

class TestGetPointsSummary:
    async def test_raises_404_when_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_points_summary(make_uuid(), user)
        assert exc.value.status_code == 404

    async def test_raises_403_non_admin_other_wallet(self):
        wallet = _fake_wallet(employee_id="owner")
        user   = _current_user(user_id="other", roles=["EMPLOYEE"])
        with patch.object(svc.db, "wallets") as mock_w:
            mock_w.find_unique = AsyncMock(return_value=wallet)
            with pytest.raises(HTTPException) as exc:
                await svc.get_points_summary(str(wallet.wallet_id), user)
        assert exc.value.status_code == 403

    async def test_returns_summary_keys(self):
        wallet = _fake_wallet(); user = _current_user()
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(return_value=[])
            result = await svc.get_points_summary(str(wallet.wallet_id), user)
        for key in ("wallet_id", "points_this_month", "points_this_year"):
            assert key in result

    async def test_sums_month_and_year_transactions(self):
        wallet = _fake_wallet(); user = _current_user()
        t1 = MagicMock(); t1.amount = 10
        t2 = MagicMock(); t2.amount = 20
        with (
            patch.object(svc.db, "wallets")      as mock_w,
            patch.object(svc.db, "transactions") as mock_t,
        ):
            mock_w.find_unique = AsyncMock(return_value=wallet)
            mock_t.find_many   = AsyncMock(side_effect=[[t1, t2], [t1, t2]])
            result = await svc.get_points_summary(str(wallet.wallet_id), user)
        assert result["points_this_month"] == 30
        assert result["points_this_year"]  == 30


# ══════════════════════════════════════════════════════════════════════════════
# credit_wallet_from_review
# ══════════════════════════════════════════════════════════════════════════════

class TestCreditWalletFromReview:
    async def test_raises_404_when_review_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(make_uuid(), user)
        assert exc.value.status_code == 404

    async def test_raises_422_when_no_raw_points(self):
        review = _fake_review(raw_points=None); user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=review)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(str(review.review_id), user)
        assert exc.value.status_code == 422

    async def test_returns_no_points_message_for_zero_points(self):
        """raw_points=0.4 rounds to 0 → early return."""
        review = _fake_review(raw_points=0.3); user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=review)
            result = await svc.credit_wallet_from_review(str(review.review_id), user)
        assert result["credited_points"] == 0

    async def test_raises_404_when_wallet_not_found(self):
        review = _fake_review(raw_points=2.6); user = _current_user()
        with (
            patch.object(svc.db, "reviews")  as mock_r,
            patch.object(svc.db, "wallets")  as mock_w,
        ):
            mock_r.find_unique = AsyncMock(return_value=review)
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(str(review.review_id), user)
        assert exc.value.status_code == 404

    async def test_raises_500_when_credit_type_missing(self):
        review = _fake_review(raw_points=2.6); user = _current_user()
        wallet = _fake_wallet(employee_id=str(review.receiver_id))
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.credit_wallet_from_review(str(review.review_id), user)
        assert exc.value.status_code == 500

    async def test_successful_credit_returns_expected_keys(self):
        review   = _fake_review(raw_points=2.6); user = _current_user()
        wallet   = _fake_wallet(employee_id=str(review.receiver_id))
        txn_type = _fake_txn_type(type_code="CREDIT")
        status   = _fake_status(status_code="APPROVED")
        new_txn  = MagicMock(transaction_id=make_uuid())
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
        for key in ("transaction_id", "wallet_id", "credited_points", "new_balance", "message"):
            assert key in result

    async def test_points_rounded_from_raw(self):
        """raw_points=2.6 → round(2.6)=3."""
        review   = _fake_review(raw_points=2.6); user = _current_user()
        wallet   = _fake_wallet(employee_id=str(review.receiver_id))
        txn_type = _fake_txn_type(type_code="CREDIT")
        status   = _fake_status(status_code="APPROVED")
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
        assert result["credited_points"] == 3

    async def test_category_label_from_tags(self):
        tag    = _fake_category_tag(code="INNOVATION")
        review = _fake_review(raw_points=1.4, tags=[tag]); user = _current_user()
        wallet = _fake_wallet(employee_id=str(review.receiver_id))
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
        assert "message" in result

    async def test_cache_invalidated_after_credit(self):
        review   = _fake_review(raw_points=2.0); user = _current_user()
        wallet   = _fake_wallet(employee_id=str(review.receiver_id))
        txn_type = _fake_txn_type(); status = _fake_status(status_code="APPROVED")
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd,
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=txn_type)
            mock_sm.find_first  = AsyncMock(return_value=status)
            await svc.credit_wallet_from_review(str(review.review_id), user)
        mock_cd.assert_awaited()


# ══════════════════════════════════════════════════════════════════════════════
# adjust_wallet_for_review_update
# ══════════════════════════════════════════════════════════════════════════════

class TestAdjustWalletForReviewUpdate:
    async def test_zero_delta_returns_early(self):
        user   = _current_user()
        result = await svc.adjust_wallet_for_review_update(make_uuid(), 0.4, user)
        assert result["credited_points"] == 0
        assert "no wallet adjustment" in result["message"].lower()

    async def test_raises_404_when_review_not_found(self):
        user = _current_user()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.adjust_wallet_for_review_update(make_uuid(), 2.0, user)
        assert exc.value.status_code == 404

    async def test_raises_404_when_wallet_not_found(self):
        review = _fake_review(); user = _current_user()
        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_r.find_unique = AsyncMock(return_value=review)
            mock_w.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.adjust_wallet_for_review_update(
                    str(review.review_id), 2.0, user)
        assert exc.value.status_code == 404

    async def test_skips_debit_when_would_go_negative(self):
        review = _fake_review(); user = _current_user()
        wallet = _fake_wallet(available_points=5)
        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "wallets") as mock_w,
        ):
            mock_r.find_unique = AsyncMock(return_value=review)
            mock_w.find_unique = AsyncMock(return_value=wallet)
            result = await svc.adjust_wallet_for_review_update(
                str(review.review_id), -10.0, user)
        assert "skipped" in result["message"].lower()
        assert result["credited_points"] == -10

    async def test_successful_positive_adjustment(self):
        review   = _fake_review(); user = _current_user()
        wallet   = _fake_wallet(available_points=100)
        txn_type = _fake_txn_type(type_code="CREDIT"); status = _fake_status(status_code="APPROVED")
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
                str(review.review_id), 3.0, user)
        assert result["credited_points"] == 3
        assert "transaction_id" in result

    async def test_cache_invalidated_after_adjust(self):
        review   = _fake_review(); user = _current_user()
        wallet   = _fake_wallet(available_points=100)
        txn_type = _fake_txn_type(type_code="CREDIT"); status = _fake_status(status_code="APPROVED")
        with (
            patch.object(svc.db, "reviews")           as mock_r,
            patch.object(svc.db, "wallets")           as mock_w,
            patch.object(svc.db, "transaction_types") as mock_tt,
            patch.object(svc.db, "status_master")     as mock_sm,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd,
            patch(f"{_SVC}._get_notif", return_value=MagicMock(create_notification=AsyncMock())),
            patch.object(svc.db, "tx", _noop_tx),
        ):
            mock_r.find_unique  = AsyncMock(return_value=review)
            mock_w.find_unique  = AsyncMock(return_value=wallet)
            mock_tt.find_unique = AsyncMock(return_value=txn_type)
            mock_sm.find_first  = AsyncMock(return_value=status)
            await svc.adjust_wallet_for_review_update(str(review.review_id), 2.0, user)
        mock_cd.assert_awaited()
