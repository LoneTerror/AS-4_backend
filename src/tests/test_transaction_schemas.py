import pytest
from uuid import uuid4
from datetime import datetime
from pydantic import ValidationError

from src.transaction.schemas import (
    TransactionCreate,
    StatusInfo,
    TransactionTypeInfo,
    TransactionResponse,
    TransactionListResponse
)


# ---------------------------------------------------------------------------
# TransactionCreate
# ---------------------------------------------------------------------------

# Ensures valid payload creates TransactionCreate model
def test_transaction_create_valid():

    data = TransactionCreate(
        wallet_id=uuid4(),
        amount=100,
        transaction_type_id=uuid4(),
        description="Test",
        reference_number="REF-123"
    )

    assert data.amount == 100
    assert data.description == "Test"


# Ensures invalid UUID raises validation error
def test_transaction_create_invalid_uuid():

    with pytest.raises(ValidationError):
        TransactionCreate(
            wallet_id="not-a-uuid",
            amount=100,
            transaction_type_id=uuid4(),
            reference_number="REF-123"
        )


# Ensures missing required field raises error
def test_transaction_create_missing_reference():

    with pytest.raises(ValidationError):
        TransactionCreate(
            wallet_id=uuid4(),
            amount=100,
            transaction_type_id=uuid4()
        )


# ---------------------------------------------------------------------------
# StatusInfo
# ---------------------------------------------------------------------------

# Ensures StatusInfo.from_db maps correctly
def test_status_info_from_db():

    class DummyStatus:
        status_id = str(uuid4())
        status_code = "SUCCESS"
        status_name = "Success"

    status = StatusInfo.from_db(DummyStatus)

    assert status.code == "SUCCESS"
    assert status.name == "Success"


# Ensures from_db returns None when input is None
def test_status_info_from_db_none():

    result = StatusInfo.from_db(None)
    assert result is None


# ---------------------------------------------------------------------------
# TransactionTypeInfo
# ---------------------------------------------------------------------------

# Ensures TransactionTypeInfo.from_db maps correctly
def test_transaction_type_info_from_db():

    class DummyType:
        type_id = str(uuid4())
        type_code = "CREDIT"
        type_name = "Credit"
        is_credit = True

    txn_type = TransactionTypeInfo.from_db(DummyType)

    assert txn_type.code == "CREDIT"
    assert txn_type.is_credit is True


# Ensures from_db returns None when input is None
def test_transaction_type_info_from_db_none():

    result = TransactionTypeInfo.from_db(None)
    assert result is None


# ---------------------------------------------------------------------------
# TransactionResponse
# ---------------------------------------------------------------------------

# Ensures valid TransactionResponse model creation
def test_transaction_response_valid():

    now = datetime.utcnow()

    response = TransactionResponse(
        transaction_id=uuid4(),
        wallet_id=uuid4(),
        amount=100,
        status={
            "status_id": str(uuid4()),
            "code": "SUCCESS",
            "name": "Success"
        },
        transaction_type={
            "type_id": str(uuid4()),
            "code": "CREDIT",
            "name": "Credit",
            "is_credit": True
        },
        reference_number="REF",
        description="Test",
        transaction_at=now,
        created_at=now,
        updated_at=now,
        created_by=uuid4(),
        updated_by=uuid4()
    )

    assert response.amount == 100
    assert response.status.code == "SUCCESS"


# Ensures invalid nested structure raises error
def test_transaction_response_invalid_nested():

    now = datetime.utcnow()

    with pytest.raises(ValidationError):
        TransactionResponse(
            transaction_id=uuid4(),
            wallet_id=uuid4(),
            amount=100,
            status={},  # invalid
            transaction_type={},  # invalid
            reference_number="REF",
            transaction_at=now,
            created_at=now,
            updated_at=now
        )


# ---------------------------------------------------------------------------
# TransactionListResponse
# ---------------------------------------------------------------------------

# Ensures list response accepts valid transactions
def test_transaction_list_response_valid():

    now = datetime.utcnow()

    txn = {
        "transaction_id": str(uuid4()),
        "wallet_id": str(uuid4()),
        "amount": 100,
        "status": {
            "status_id": str(uuid4()),
            "code": "SUCCESS",
            "name": "Success"
        },
        "transaction_type": {
            "type_id": str(uuid4()),
            "code": "CREDIT",
            "name": "Credit",
            "is_credit": True
        },
        "reference_number": "REF",
        "description": "Test",
        "transaction_at": now,
        "created_at": now,
        "updated_at": now,
        "created_by": str(uuid4()),
        "updated_by": str(uuid4())
    }

    response = TransactionListResponse(
        page=1,
        limit=10,
        total=1,
        transactions=[txn]
    )

    assert response.total == 1
    assert len(response.transactions) == 1


# Ensures invalid transaction list entry raises error
def test_transaction_list_response_invalid_transaction():

    with pytest.raises(ValidationError):
        TransactionListResponse(
            page=1,
            limit=10,
            total=1,
            transactions=[{}]  # invalid structure
        )