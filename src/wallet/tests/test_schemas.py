"""
src/wallet/tests/test_schemas.py
──────────────────────────────────
Pydantic schema validation tests for src/wallet/schemas.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime
import pytest
from pydantic import ValidationError

from src.wallet.schemas import (
    ReviewCreditRequest,
    ReviewCreditResponse,
    TransactionCreate,
    StatusInfo,
    TransactionTypeInfo,
    TransactionResponse,
    TransactionListResponse,
    WalletResponse,
    WalletBalanceResponse,
)

W_ID = uuid.uuid4()
E_ID = uuid.uuid4()
T_ID = uuid.uuid4()
TT_ID = uuid.uuid4()
STAT_ID = str(uuid.uuid4())
TYPE_ID = str(uuid.uuid4())
NOW = datetime(2026, 1, 15, 10, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCreditRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCreditRequest:
    def _valid(self, **ov):
        base = dict(employee_id=E_ID, rating=3, review_id=T_ID, created_by=W_ID)
        base.update(ov); return ReviewCreditRequest(**base)

    def test_valid(self):
        r = self._valid(); assert r.rating == 3

    def test_all_fields_uuid(self):
        r = self._valid()
        assert r.employee_id == E_ID
        assert r.review_id   == T_ID
        assert r.created_by  == W_ID

    def test_missing_employee_id_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreditRequest(rating=3, review_id=T_ID, created_by=W_ID)

    def test_missing_review_id_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreditRequest(employee_id=E_ID, rating=3, created_by=W_ID)

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(employee_id="not-a-uuid")

    def test_rating_stored(self):
        r = self._valid(rating=5); assert r.rating == 5


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCreditResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCreditResponse:
    def _valid(self, **ov):
        base = dict(transaction_id=T_ID, wallet_id=W_ID, credited_points=10,
                    message="10 points credited")
        base.update(ov); return ReviewCreditResponse(**base)

    def test_valid(self):
        r = self._valid(); assert r.credited_points == 10

    def test_missing_transaction_id_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreditResponse(wallet_id=W_ID, credited_points=10, message="ok")

    def test_message_stored(self):
        r = self._valid(message="Points added"); assert r.message == "Points added"


# ─────────────────────────────────────────────────────────────────────────────
# TransactionCreate
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionCreate:
    def _valid(self, **ov):
        base = dict(wallet_id=W_ID, amount=100, transaction_type_id=TT_ID,
                    reference_number="REF-001")
        base.update(ov); return TransactionCreate(**base)

    def test_valid(self):
        r = self._valid(); assert r.amount == 100

    def test_description_optional(self):
        r = self._valid(); assert r.description is None

    def test_description_provided(self):
        r = self._valid(description="Manual credit"); assert r.description == "Manual credit"

    def test_missing_wallet_id_raises(self):
        with pytest.raises(ValidationError):
            TransactionCreate(amount=100, transaction_type_id=TT_ID, reference_number="R")

    def test_missing_amount_raises(self):
        with pytest.raises(ValidationError):
            TransactionCreate(wallet_id=W_ID, transaction_type_id=TT_ID, reference_number="R")

    def test_missing_reference_number_raises(self):
        with pytest.raises(ValidationError):
            TransactionCreate(wallet_id=W_ID, amount=100, transaction_type_id=TT_ID)

    def test_invalid_wallet_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(wallet_id="not-a-uuid")

    def test_all_fields_present(self):
        r = self._valid()
        for f in ("wallet_id","amount","transaction_type_id","reference_number"):
            assert getattr(r, f) is not None


# ─────────────────────────────────────────────────────────────────────────────
# StatusInfo
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusInfo:
    def test_valid(self):
        s = StatusInfo(status_id=STAT_ID, code="APPROVED", name="Approved")
        assert s.code == "APPROVED"

    def test_from_db_none_returns_none(self):
        assert StatusInfo.from_db(None) is None

    def test_from_db_object(self):
        from unittest.mock import MagicMock
        obj = MagicMock()
        obj.status_id = STAT_ID; obj.status_code = "SUCCESS"; obj.status_name = "Success"
        s = StatusInfo.from_db(obj)
        assert s.code == "SUCCESS"

    def test_missing_status_id_raises(self):
        with pytest.raises(ValidationError):
            StatusInfo(code="X", name="X")


# ─────────────────────────────────────────────────────────────────────────────
# TransactionTypeInfo
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionTypeInfo:
    def test_valid_credit(self):
        t = TransactionTypeInfo(type_id=TYPE_ID, code="CREDIT", name="Credit", is_credit=True)
        assert t.is_credit is True

    def test_valid_debit(self):
        t = TransactionTypeInfo(type_id=TYPE_ID, code="DEBIT", name="Debit", is_credit=False)
        assert t.is_credit is False

    def test_from_db_none_returns_none(self):
        assert TransactionTypeInfo.from_db(None) is None

    def test_from_db_object(self):
        from unittest.mock import MagicMock
        obj = MagicMock()
        obj.type_id = TYPE_ID; obj.type_code = "CREDIT"; obj.type_name = "Credit"; obj.is_credit = True
        t = TransactionTypeInfo.from_db(obj)
        assert t.code == "CREDIT"
        assert t.is_credit is True

    def test_missing_is_credit_raises(self):
        with pytest.raises(ValidationError):
            TransactionTypeInfo(type_id=TYPE_ID, code="X", name="X")


# ─────────────────────────────────────────────────────────────────────────────
# TransactionResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionResponse:
    def _status(self):
        return StatusInfo(status_id=STAT_ID, code="APPROVED", name="Approved")

    def _txn_type(self):
        return TransactionTypeInfo(type_id=TYPE_ID, code="CREDIT", name="Credit", is_credit=True)

    def _make(self, **ov):
        base = dict(
            transaction_id=T_ID, wallet_id=W_ID, amount=50,
            status=self._status(), transaction_type=self._txn_type(),
            reference_number="REF-001", description=None,
            transaction_at=NOW, created_at=NOW, updated_at=NOW,
        )
        base.update(ov); return TransactionResponse(**base)

    def test_valid(self):
        r = self._make(); assert r.amount == 50

    def test_description_optional(self):
        r = self._make(); assert r.description is None

    def test_created_by_optional(self):
        r = self._make(); assert r.created_by is None

    def test_nested_status(self):
        r = self._make(); assert r.status.code == "APPROVED"

    def test_nested_transaction_type(self):
        r = self._make(); assert r.transaction_type.is_credit is True

    def test_missing_transaction_id_raises(self):
        with pytest.raises(ValidationError):
            TransactionResponse(
                wallet_id=W_ID, amount=50, status=self._status(),
                transaction_type=self._txn_type(), reference_number="R",
                transaction_at=NOW, created_at=NOW, updated_at=NOW,
            )


# ─────────────────────────────────────────────────────────────────────────────
# TransactionListResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestTransactionListResponse:
    def test_valid_empty(self):
        r = TransactionListResponse(page=1, limit=10, total=0, transactions=[])
        assert r.total == 0; assert r.transactions == []

    def test_missing_page_raises(self):
        with pytest.raises(ValidationError):
            TransactionListResponse(limit=10, total=0, transactions=[])

    def test_pagination_fields(self):
        r = TransactionListResponse(page=2, limit=20, total=50, transactions=[])
        assert r.page == 2; assert r.limit == 20


# ─────────────────────────────────────────────────────────────────────────────
# WalletResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestWalletResponse:
    def test_valid(self):
        r = WalletResponse(wallet_id=W_ID, employee_id=E_ID,
                           available_points=100, redeemed_points=0, total_earned_points=100)
        assert r.available_points == 100

    def test_missing_wallet_id_raises(self):
        with pytest.raises(ValidationError):
            WalletResponse(employee_id=E_ID, available_points=0,
                           redeemed_points=0, total_earned_points=0)

    def test_all_point_fields(self):
        r = WalletResponse(wallet_id=W_ID, employee_id=E_ID,
                           available_points=300, redeemed_points=50, total_earned_points=350)
        assert r.redeemed_points == 50


# ─────────────────────────────────────────────────────────────────────────────
# WalletBalanceResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestWalletBalanceResponse:
    def test_valid(self):
        r = WalletBalanceResponse(wallet_id=W_ID, available_points=250)
        assert r.available_points == 250

    def test_missing_wallet_id_raises(self):
        with pytest.raises(ValidationError):
            WalletBalanceResponse(available_points=100)

    def test_zero_points_ok(self):
        r = WalletBalanceResponse(wallet_id=W_ID, available_points=0)
        assert r.available_points == 0
