import pytest
from uuid import uuid4
from datetime import datetime
from pydantic import ValidationError

# Ensures ReviewCreditRequest accepts valid UUIDs and rating
def test_review_credit_request_valid():
    from src.wallet.schemas import ReviewCreditRequest

    data = ReviewCreditRequest(
        employee_id=uuid4(),
        rating=5,
        review_id=uuid4(),
        created_by=uuid4()
    )

    assert data.rating == 5

# Ensures ReviewCreditRequest fails with invalid UUID

def test_review_credit_request_invalid_uuid():
    from src.wallet.schemas import ReviewCreditRequest

    with pytest.raises(Exception):
        ReviewCreditRequest(
            employee_id="not-a-uuid",
            rating=5,
            review_id="also-not",
            created_by="bad"
        )

# Ensures missing required fields raise validation error
def test_review_credit_request_missing_field():
    from uuid import uuid4
    from src.wallet.schemas import ReviewCreditRequest
    import pytest

    with pytest.raises(Exception):
        ReviewCreditRequest(
            employee_id=uuid4(),
            rating=5,
            review_id=uuid4()
            # created_by missing
        )

# Ensures ReviewCreditResponse accepts valid data
def test_review_credit_response_valid():
    from uuid import uuid4
    from src.wallet.schemas import ReviewCreditResponse

    data = ReviewCreditResponse(
        transaction_id=uuid4(),
        wallet_id=uuid4(),
        credited_points=50,
        message="Points credited"
    )

    assert data.credited_points == 50

# Ensures WalletResponse schema validates properly
def test_wallet_response_valid():
    from uuid import uuid4
    from src.wallet.schemas import WalletResponse

    wallet = WalletResponse(
        wallet_id=uuid4(),
        employee_id=uuid4(),
        available_points=100,
        redeemed_points=20,
        total_earned_points=120
    )

    assert wallet.available_points == 100

# Ensures WalletResponse fails on invalid types
def test_wallet_response_invalid_type():
    from src.wallet.schemas import WalletResponse
    import pytest

    with pytest.raises(Exception):
        WalletResponse(
            wallet_id="bad",
            employee_id="bad",
            available_points="a lot",
            redeemed_points=20,
            total_earned_points=120
        )

# Ensures WalletBalanceResponse validates correctly
def test_wallet_balance_response_valid():
    from uuid import uuid4
    from src.wallet.schemas import WalletBalanceResponse

    balance = WalletBalanceResponse(
        wallet_id=uuid4(),
        available_points=500
    )

    assert balance.available_points == 500

# Ensures CreditFromReviewRequest accepts string review_id
def test_credit_from_review_request_valid():
    from src.wallet.schemas import CreditFromReviewRequest

    req = CreditFromReviewRequest(review_id="rev-123")
    assert req.review_id == "rev-123"

# Ensures CreditFromReviewRequest fails if review_id missing
def test_credit_from_review_request_missing():
    from src.wallet.schemas import CreditFromReviewRequest
    import pytest

    with pytest.raises(Exception):
        CreditFromReviewRequest()