import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from prisma.errors import UniqueViolationError

from src.transaction.service import create_transaction


class DummyUser:
    def __init__(self, roles):
        self.id = "admin-id"
        self.roles = roles


class DummyData:
    def __init__(self, amount=100):
        self.wallet_id = "wallet-1"
        self.transaction_type_id = "type-1"
        self.amount = amount
        self.description = "Test"
        self.reference_number = "REF-123"


# -------------------------
# Invalid amount -> 400
# -------------------------
@pytest.mark.asyncio
async def test_create_transaction_invalid_amount():
    user = DummyUser(["HR_ADMIN"])
    data = DummyData(amount=0)

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 400


# -------------------------
# Wallet not found -> 404
# -------------------------
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_create_transaction_wallet_not_found(mock_db):
    user = DummyUser(["HR_ADMIN"])
    data = DummyData()

    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Wallet not found"


# -------------------------
# Transaction type not found -> 404
# -------------------------
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_create_transaction_type_not_found(mock_db):
    user = DummyUser(["HR_ADMIN"])
    data = DummyData()

    mock_wallet = AsyncMock()
    mock_wallet.available_points = 500
    mock_wallet.redeemed_points = 0
    mock_wallet.total_earned_points = 500
    mock_wallet.version = 1
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Transaction type not found"


# -------------------------
# SUCCESS status missing -> 500
# -------------------------
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_create_transaction_missing_success_status(mock_db):
    user = DummyUser(["HR_ADMIN"])
    data = DummyData()

    mock_wallet = AsyncMock()
    mock_wallet.available_points = 500
    mock_wallet.redeemed_points = 0
    mock_wallet.total_earned_points = 500
    mock_wallet.version = 1
    mock_wallet.employee_id = "admin-id"

    mock_type = AsyncMock()
    mock_type.is_credit = True

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_unique = AsyncMock(return_value=None)
    mock_db.status_master.find_many = AsyncMock(return_value=[])

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 500


# -------------------------
# Concurrency conflict -> 409
# -------------------------
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_create_transaction_concurrency_conflict(mock_db):
    user = DummyUser(["HR_ADMIN"])
    data = DummyData()

    mock_wallet = AsyncMock()
    mock_wallet.available_points = 500
    mock_wallet.redeemed_points = 0
    mock_wallet.total_earned_points = 500
    mock_wallet.version = 1
    mock_wallet.employee_id = "admin-id"

    mock_type = AsyncMock()
    mock_type.is_credit = True

    mock_status = AsyncMock()
    mock_status.status_id = "status-success"

    mock_txn = AsyncMock()
    mock_txn.transaction_id = "txn-1"

    mock_tx_context = AsyncMock()
    mock_tx_context.transactions.create = AsyncMock(return_value=mock_txn)
    mock_tx_context.wallets.update_many = AsyncMock(return_value=0)

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_unique = AsyncMock(return_value=mock_status)
    mock_db.status_master.find_many = AsyncMock(return_value=[])
    mock_db.tx.return_value.__aenter__.return_value = mock_tx_context

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 409


# -------------------------
# Duplicate reference -> 409
# -------------------------
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_create_transaction_duplicate_reference(mock_db):
    user = DummyUser(["HR_ADMIN"])
    data = DummyData()

    mock_wallet = AsyncMock()
    mock_wallet.available_points = 500
    mock_wallet.redeemed_points = 0
    mock_wallet.total_earned_points = 500
    mock_wallet.version = 1
    mock_wallet.employee_id = "admin-id"

    mock_type = AsyncMock()
    mock_type.is_credit = True

    mock_status = AsyncMock()
    mock_status.status_id = "status-success"

    mock_tx_context = AsyncMock()
    mock_tx_context.transactions.create = AsyncMock(
        side_effect=UniqueViolationError({})
    )
    mock_tx_context.wallets.update_many = AsyncMock(return_value=1)

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_unique = AsyncMock(return_value=mock_status)
    mock_db.status_master.find_many = AsyncMock(return_value=[])
    mock_db.tx.return_value.__aenter__.return_value = mock_tx_context

    with pytest.raises(HTTPException) as exc:
        await create_transaction(data, user)

    assert exc.value.status_code == 409


# Wallet not found -> 404 (get_transactions)

@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_wallet_not_found(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await get_transactions(
            wallet_id="wallet-1",
            page=1,
            limit=10,
            current_user=user
        )

    assert exc.value.status_code == 404

# Successful fetch returns formatted structure

@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_success(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"
    mock_status.status_code = "SUCCESS"
    mock_status.status_name = "Successful"

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"
    mock_type.type_code = "CREDIT"
    mock_type.type_name = "Credit"
    mock_type.is_credit = True

    mock_txn = AsyncMock()
    mock_txn.transaction_id = "txn-1"
    mock_txn.wallet_id = "wallet-1"
    mock_txn.amount = 100
    mock_txn.status_master = mock_status
    mock_txn.transaction_types = mock_type
    mock_txn.reference_number = "REF-123"
    mock_txn.description = "Test"
    mock_txn.transaction_at = None
    mock_txn.created_at = None
    mock_txn.updated_at = None
    mock_txn.created_by = "admin-id"
    mock_txn.updated_by = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(return_value=[mock_txn])
    mock_db.transactions.count = AsyncMock(return_value=1)

    result = await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=10,
        current_user=user
    )

    assert result["total"] == 1
    assert result["transactions"][0]["transaction_id"] == "txn-1"
    assert result["transactions"][0]["status"]["code"] == "SUCCESS"
    assert result["transactions"][0]["transaction_type"]["code"] == "CREDIT"

# Ensures page values less than 1 are normalized to 1(get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_page_normalization(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    result = await get_transactions(
        wallet_id="wallet-1",
        page=0,
        limit=10,
        current_user=user
    )

    assert result["page"] == 1

# Ensures limit values greater than 100 are capped at 100 (get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_limit_cap(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    result = await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=1000,
        current_user=user
    )

    assert result["limit"] == 100

# Ensures status_code filter resolves correctly and applies status_id to the query(get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_status_filter(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.status_master.find_unique = AsyncMock(return_value=mock_status)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=10,
        current_user=user,
        status_code="SUCCESS"
    )

    mock_db.status_master.find_unique.assert_called_once()

# Ensures date range filters are passed into the transaction query(get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_date_filter(mock_db):
    from src.transaction.service import get_transactions
    from datetime import datetime

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    start = datetime(2024, 1, 1)
    end = datetime(2024, 12, 31)

    await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=10,
        current_user=user,
        start_date=start,
        end_date=end
    )

    mock_db.transactions.find_many.assert_called_once()

# Ensures non-admin users can access their own wallet transactions(get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_non_admin_own_wallet(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["EMPLOYEE"])
    user.id = "user-1"

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "user-1"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    result = await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=10,
        current_user=user
    )

    assert result["total"] == 0

# Ensures providing an invalid status_code does not break the query logic(get_transaction)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transactions_invalid_status_filter(mock_db):
    from src.transaction.service import get_transactions

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.status_master.find_unique = AsyncMock(return_value=None)
    mock_db.transactions.find_many = AsyncMock(return_value=[])
    mock_db.transactions.count = AsyncMock(return_value=0)

    result = await get_transactions(
        wallet_id="wallet-1",
        page=1,
        limit=10,
        current_user=user,
        status_code="DOES_NOT_EXIST"
    )

    assert result["total"] == 0

# Ensures requesting a non-existent transaction returns 404(get_transaction_by_id)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_by_id_not_found(mock_db):
    from src.transaction.service import get_transaction_by_id

    user = DummyUser(["HR_ADMIN"])

    mock_db.transactions.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await get_transaction_by_id("txn-1", user)

    assert exc.value.status_code == 404

# Ensures non-admin users cannot access transactions of other users(get_transaction_by_id)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_by_id_access_denied(mock_db):
    from src.transaction.service import get_transaction_by_id

    user = DummyUser(["EMPLOYEE"])
    user.id = "user-1"

    mock_txn = AsyncMock()
    mock_txn.wallet_id = "wallet-1"

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "someone-else"

    mock_db.transactions.find_unique = AsyncMock(return_value=mock_txn)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)

    with pytest.raises(HTTPException) as exc:
        await get_transaction_by_id("txn-1", user)

    assert exc.value.status_code == 403

# Ensures successful transaction fetch returns properly formatted response(get_transaction_by_id)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_by_id_success(mock_db):
    from src.transaction.service import get_transaction_by_id

    user = DummyUser(["HR_ADMIN"])

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"
    mock_status.status_code = "SUCCESS"
    mock_status.status_name = "Successful"

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"
    mock_type.type_code = "CREDIT"
    mock_type.type_name = "Credit"
    mock_type.is_credit = True

    mock_txn = AsyncMock()
    mock_txn.transaction_id = "txn-1"
    mock_txn.wallet_id = "wallet-1"
    mock_txn.amount = 100
    mock_txn.status_master = mock_status
    mock_txn.transaction_types = mock_type
    mock_txn.reference_number = "REF-123"
    mock_txn.description = "Test"
    mock_txn.transaction_at = None
    mock_txn.created_at = None
    mock_txn.updated_at = None
    mock_txn.created_by = "admin-id"
    mock_txn.updated_by = "admin-id"

    mock_db.transactions.find_unique = AsyncMock(return_value=mock_txn)

    result = await get_transaction_by_id("txn-1", user)

    assert result["transaction_id"] == "txn-1"
    assert result["status"].code == "SUCCESS"

# Ensures non-admin users cannot fetch transaction types(get_transaction_types)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_types_access_denied(mock_db):
    from src.transaction.service import get_transaction_types

    user = DummyUser(["EMPLOYEE"])

    with pytest.raises(HTTPException) as exc:
        await get_transaction_types(user)

    assert exc.value.status_code == 403

# Ensures admin users can successfully fetch and format transaction types(get_transactio_types)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_types_success(mock_db):
    from src.transaction.service import get_transaction_types

    user = DummyUser(["HR_ADMIN"])

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"
    mock_type.type_code = "CREDIT"
    mock_type.type_name = "Credit"
    mock_type.is_credit = True

    mock_db.transaction_types.find_many = AsyncMock(return_value=[mock_type])

    result = await get_transaction_types(user)

    assert len(result) == 1
    assert result[0]["code"] == "CREDIT"
    assert result[0]["is_credit"] is True

# Ensures empty transaction types list returns an empty response(get_transaction_types)
@pytest.mark.asyncio
@patch("src.transaction.service.db")
async def test_get_transaction_types_empty(mock_db):
    from src.transaction.service import get_transaction_types

    user = DummyUser(["HR_ADMIN"])

    mock_db.transaction_types.find_many = AsyncMock(return_value=[])

    result = await get_transaction_types(user)

    assert result == []