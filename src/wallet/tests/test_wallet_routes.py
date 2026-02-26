import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.wallet.routes import router

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)


    from src.wallet.dependencies import get_current_user

    class DummyUser:
        def __init__(self):
            self.id = "admin-id"
            self.roles = ["HR_ADMIN"]

    app.dependency_overrides[get_current_user] = lambda: DummyUser()

    return TestClient(app)

#Ensure wallet fetch endpoint returns 200 with service result (get_wallet_by_employee)
@patch("src.wallet.routes.get_wallet_by_employee", new_callable=AsyncMock)
def test_get_wallet_success(mock_service, client):
    mock_service.return_value = {"wallet_id": "wallet-1"}

    response = client.get(
        "/wallets/employees/emp-1",
        headers={"Authorization": "Bearer test-token"}
    )

    assert response.status_code == 200
    assert response.json()["wallet_id"] == "wallet-1"


# Ensures wallet balance endpoint returns correct response (get_wallet_balance)
@patch("src.wallet.routes.get_wallet_balance", new_callable=AsyncMock)
def test_get_wallet_balance_success(mock_service, client):
    from uuid import uuid4
    wallet_id = str(uuid4())
    mock_service.return_value = {
        "wallet_id": wallet_id,
        "available_points": 500
    }

    response = client.get(
        f"/wallets/{wallet_id}/balance"
    )

    assert response.status_code == 200
    assert response.json()["available_points"] == 500

# Ensures points summary endpoint returns aggregated data (get_points_summary)
@patch("src.wallet.routes.get_points_summary", new_callable=AsyncMock)
def test_points_summary_success(mock_service, client):
    mock_service.return_value = {
        "wallet_id": "123e4567-e89b-12d3-a456-426614174000",
        "points_this_month": 100,
        "points_this_year": 200
    }

    response = client.get("/wallets/wallet-1/points-summary")

    assert response.status_code == 200
    assert response.json()["points_this_year"] == 200

# Ensures internal route rejects missing API key (credit_from_review)
def test_credit_from_review_missing_header(client):
    response = client.post("/internal/credit-from-review?review_id=rev-1")

    assert response.status_code == 403

# Ensures internal route rejects incorrect API key (credit_from_review)
def test_credit_from_review_wrong_key(client):
    response = client.post(
        "/internal/credit-from-review?review_id=rev-1",
        headers={"x-internal-api-key": "wrong"}
    )

    assert response.status_code == 403

# Ensures internal credit endpoint calls service with valid key (credit_wallet_from_review)
@patch("src.wallet.routes.credit_wallet_from_review", new_callable=AsyncMock)
def test_credit_from_review_success(mock_service, client):
    from src.core.security import SECRET_KEY

    mock_service.return_value = {"message": "ok"}

    response = client.post(
        "/internal/credit-from-review?review_id=rev-1",
        headers={"x-internal-api-key": SECRET_KEY}
    )

    assert response.status_code == 200
    mock_service.assert_awaited_once_with("rev-1")

# Ensures balance endpoint returns 404 when service raises Wallet not found (get_wallet_balance)
@patch("src.wallet.routes.get_wallet_balance", new_callable=AsyncMock)
def test_get_wallet_balance_not_found(mock_service, client):
    from fastapi import HTTPException
    mock_service.side_effect = HTTPException(status_code=404, detail="Wallet not found")

    from uuid import uuid4
    wallet_id = str(uuid4())

    response = client.get(f"/wallets/{wallet_id}/balance")

    assert response.status_code == 404
    assert response.json()["detail"] == "Wallet not found"

# Ensures balance endpoint returns 403 when access denied (get_wallet_balance)
@patch("src.wallet.routes.get_wallet_balance", new_callable=AsyncMock)
def test_get_wallet_balance_forbidden(mock_service, client):
    from fastapi import HTTPException
    mock_service.side_effect = HTTPException(status_code=403, detail="Access denied")

    from uuid import uuid4
    wallet_id = str(uuid4())

    response = client.get(f"/wallets/{wallet_id}/balance")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"

# Ensures invalid UUID in path returns 422 validation error 
def test_get_wallet_balance_invalid_uuid(client):
    response = client.get("/wallets/not-a-uuid/balance")
    assert response.status_code == 422

# Ensures points summary endpoint propagates 403 from service (get_points_summary)
@patch("src.wallet.routes.get_points_summary", new_callable=AsyncMock)
def test_points_summary_forbidden(mock_service, client):
    from fastapi import HTTPException
    mock_service.side_effect = HTTPException(status_code=403, detail="Access denied")

    response = client.get("/wallets/wallet-1/points-summary")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"

# Ensures points summary endpoint propagates 404 from service (get_points_summary)
@patch("src.wallet.routes.get_points_summary", new_callable=AsyncMock)
def test_points_summary_not_found(mock_service, client):
    from fastapi import HTTPException
    mock_service.side_effect = HTTPException(status_code=404, detail="Wallet not found")

    response = client.get("/wallets/wallet-1/points-summary")

    assert response.status_code == 404
    assert response.json()["detail"] == "Wallet not found"

# Ensures internal route fails validation if review_id missing (credit_from_review)
def test_credit_from_review_missing_query_param(client):
    from src.core.security import SECRET_KEY

    response = client.post(
        "/internal/credit-from-review",
        headers={"x-internal-api-key": SECRET_KEY}
    )

    assert response.status_code == 422

# Ensures internal route propagates 404 from service (credit_from_review)
@patch("src.wallet.routes.credit_wallet_from_review", new_callable=AsyncMock)
def test_credit_from_review_not_found(mock_service, client):
    from fastapi import HTTPException
    from src.core.security import SECRET_KEY

    mock_service.side_effect = HTTPException(status_code=404, detail="Review not found")

    response = client.post(
        "/internal/credit-from-review?review_id=rev-1",
        headers={"x-internal-api-key": SECRET_KEY}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Review not found"

# Ensures employee wallet fetch propagates 403 from service (get_wallet_by_employee)
@patch("src.wallet.routes.get_wallet_by_employee", new_callable=AsyncMock)
def test_get_wallet_forbidden(mock_service, client):
    from fastapi import HTTPException
    mock_service.side_effect = HTTPException(status_code=403, detail="Access denied")

    response = client.get("/wallets/employees/emp-1")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access denied"