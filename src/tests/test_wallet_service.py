import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from prisma.errors import UniqueViolationError

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

# Ensures non-admin users cannot access other employees' wallets (get_wallet_by_employee)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_by_employee_access_denied(mock_db):
    from src.wallet.service import get_wallet_by_employee

    user = DummyUser(["EMPLOYEE"])
    user.id = "user-1"

    with pytest.raises(HTTPException) as exc:
        await get_wallet_by_employee("someone-else", user)

    assert exc.value.status_code == 403

# Ensures 404 is returned when wallet does not exist (get_wallet_by_employee)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_by_employee_not_found(mock_db):
    from src.wallet.service import get_wallet_by_employee

    user = DummyUser(["HR_ADMIN"])
    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await get_wallet_by_employee("emp-1", user)

    assert exc.value.status_code == 404

# Ensures successful wallet fetch for admin (get_wallet_by_employee)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_by_employee_success(mock_db):
    from src.wallet.service import get_wallet_by_employee

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)

    result = await get_wallet_by_employee("emp-1", user)

    assert result.wallet_id == "wallet-1"

# Ensures wallet balance returns 404 if wallet not found (get_wallet_balance)

@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_balance_not_found(mock_db):
    from src.wallet.service import get_wallet_balance

    user = DummyUser(["HR_ADMIN"])
    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await get_wallet_balance("wallet-1", user)

    assert exc.value.status_code == 404

# Ensures non-admin users cannot access other wallet balances (get_wallet_balance)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_balance_access_denied(mock_db):
    from src.wallet.service import get_wallet_balance

    user = DummyUser(["EMPLOYEE"])
    user.id = "user-1"

    mock_wallet = AsyncMock()
    mock_wallet.employee_id = "someone-else"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)

    with pytest.raises(HTTPException) as exc:
        await get_wallet_balance("wallet-1", user)

    assert exc.value.status_code == 403

# Ensures successful wallet balance response (get_wallet_balance)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_wallet_balance_success(mock_db):
    from src.wallet.service import get_wallet_balance

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 500
    mock_wallet.employee_id = "admin-id"

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)

    result = await get_wallet_balance("wallet-1", user)

    assert result["available_points"] == 500

# Ensures 404 when wallet not found in points summary (get_points_summary)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_points_summary_not_found(mock_db):
    from src.wallet.service import get_points_summary

    user = DummyUser(["HR_ADMIN"])
    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException):
        await get_points_summary("wallet-1", user)

# Ensures correct monthly and yearly points aggregation (get_points_summary)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_get_points_summary_success(mock_db):
    from src.wallet.service import get_points_summary

    user = DummyUser(["HR_ADMIN"])

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.employee_id = "admin-id"

    mock_txn1 = AsyncMock()
    mock_txn1.amount = 100

    mock_txn2 = AsyncMock()
    mock_txn2.amount = 50

    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transactions.find_many = AsyncMock(side_effect=[
        [mock_txn1],  # month
        [mock_txn1, mock_txn2]  # year
    ])

    result = await get_points_summary("wallet-1", user)

    assert result["points_this_month"] == 100
    assert result["points_this_year"] == 150

# Ensures 404 is returned when review does not exist (credit_wallet_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_review_not_found(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_db.reviews.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 404

# Ensures no transaction occurs when rating results in zero points (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_zero_points(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 1
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)

    result = await credit_wallet_from_review("review-1")

    assert result["credited_points"] == 0

# Ensures 404 when wallet for review receiver does not exist (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_wallet_not_found(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 404

# Ensures 500 when CREDIT transaction type is missing (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_credit_type_missing(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 0
    mock_wallet.total_earned_points = 0
    mock_wallet.version = 1

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 500

# Ensures 500 when APPROVED status is missing (credit_wallet_from_points)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_status_missing(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 0
    mock_wallet.total_earned_points = 0
    mock_wallet.version = 1

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_first = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 500

# Ensures 409 when wallet version update fails due to concurrency (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_concurrency_conflict(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 0
    mock_wallet.total_earned_points = 0
    mock_wallet.version = 1

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"

    mock_tx_context = AsyncMock()
    mock_tx_context.transactions.create = AsyncMock()
    mock_tx_context.wallets.update_many = AsyncMock(return_value=0)

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_first = AsyncMock(return_value=mock_status)
    mock_db.tx.return_value.__aenter__.return_value = mock_tx_context

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 409

# Ensures duplicate review credit attempts return 409 (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_duplicate_review(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 0
    mock_wallet.total_earned_points = 0
    mock_wallet.version = 1

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"

    mock_tx_context = AsyncMock()
    mock_tx_context.transactions.create = AsyncMock(
        side_effect=UniqueViolationError({})
    )
    mock_tx_context.wallets.update_many = AsyncMock(return_value=1)

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_first = AsyncMock(return_value=mock_status)
    mock_db.tx.return_value.__aenter__.return_value = mock_tx_context

    with pytest.raises(HTTPException) as exc:
        await credit_wallet_from_review("review-1")

    assert exc.value.status_code == 409

# Ensures successful review credit creates transaction and updates wallet (credit_wallet_from_review)
@pytest.mark.asyncio
@patch("src.wallet.service.db")
async def test_credit_wallet_success(mock_db):
    from src.wallet.service import credit_wallet_from_review

    mock_review = AsyncMock()
    mock_review.rating = 5
    mock_review.receiver_id = "emp-1"
    mock_review.created_by = "admin-id"

    mock_wallet = AsyncMock()
    mock_wallet.wallet_id = "wallet-1"
    mock_wallet.available_points = 0
    mock_wallet.total_earned_points = 0
    mock_wallet.version = 1

    mock_type = AsyncMock()
    mock_type.type_id = "type-1"

    mock_status = AsyncMock()
    mock_status.status_id = "status-1"

    mock_txn = AsyncMock()
    mock_txn.transaction_id = "txn-1"

    mock_tx_context = AsyncMock()
    mock_tx_context.transactions.create = AsyncMock(return_value=mock_txn)
    mock_tx_context.wallets.update_many = AsyncMock(return_value=1)

    mock_db.reviews.find_unique = AsyncMock(return_value=mock_review)
    mock_db.wallets.find_unique = AsyncMock(return_value=mock_wallet)
    mock_db.transaction_types.find_unique = AsyncMock(return_value=mock_type)
    mock_db.status_master.find_first = AsyncMock(return_value=mock_status)
    mock_db.tx.return_value.__aenter__.return_value = mock_tx_context

    result = await credit_wallet_from_review("review-1")

    assert result.transaction_id == "txn-1"

