import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from src.transaction.routes import router
from src.transaction.dependencies import get_current_user, CurrentUser


# ---------------------------------------------------------------------------
# Test Client Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)

    def dummy_user():
        return CurrentUser(
            id=str(uuid4()),
            email="admin@test.com",
            roles=["HR_ADMIN"]
        )

    app.dependency_overrides[get_current_user] = dummy_user

    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /transactions
# ---------------------------------------------------------------------------

# Ensures transaction creation returns 200 and formatted response
@patch("src.transaction.routes.create_transaction", new_callable=AsyncMock)
def test_create_transaction_success(mock_service, client):

    txn_id = str(uuid4())
    wallet_id = str(uuid4())
    user_id = str(uuid4())

    mock_txn = MagicMock()
    mock_txn.transaction_id = txn_id
    mock_txn.wallet_id = wallet_id
    mock_txn.amount = 100
    mock_txn.reference_number = "REF-1"
    mock_txn.description = "Test"
    mock_txn.transaction_at = datetime.utcnow()
    mock_txn.created_at = datetime.utcnow()
    mock_txn.updated_at = datetime.utcnow()
    mock_txn.created_by = user_id
    mock_txn.updated_by = user_id

    mock_txn.status_master = MagicMock()
    mock_txn.status_master.status_id = uuid4()
    mock_txn.status_master.status_code = "SUCCESS"
    mock_txn.status_master.status_name = "Success"

    mock_txn.transaction_types = MagicMock()
    mock_txn.transaction_types.type_id = uuid4()
    mock_txn.transaction_types.type_code = "CREDIT"
    mock_txn.transaction_types.type_name = "Credit"
    mock_txn.transaction_types.is_credit = True

    mock_service.return_value = mock_txn

    payload = {
        "wallet_id": wallet_id,
        "transaction_type_id": str(uuid4()),
        "amount": 100,
        "description": "Test",
        "reference_number": "REF-1"
    }

    response = client.post("/transactions", json=payload)

    assert response.status_code == 200
    assert response.json()["transaction_id"] == txn_id


# Ensures non-admin users get 403 on create transaction
def test_create_transaction_forbidden():

    app = FastAPI()
    app.include_router(router)

    from src.transaction.dependencies import get_current_user

    def employee_user():
        return CurrentUser(
            id=str(uuid4()),
            email="emp@test.com",
            roles=["EMPLOYEE"]
        )

    app.dependency_overrides[get_current_user] = employee_user

    client = TestClient(app)

    payload = {
        "wallet_id": str(uuid4()),
        "transaction_type_id": str(uuid4()),
        "amount": 100,
        "description": "Test",
        "reference_number": "REF"
    }

    response = client.post("/transactions", json=payload)

    assert response.status_code == 403

# Ensures missing required fields trigger 422
def test_create_transaction_validation_error(client):

    payload = {
        "wallet_id": str(uuid4()),
        # transaction_type_id missing
        "amount": 100
    }

    response = client.post("/transactions", json=payload)

    assert response.status_code == 422

# ---------------------------------------------------------------------------
# GET /transactions/types
# ---------------------------------------------------------------------------

# Ensures transaction types endpoint returns list
@patch("src.transaction.routes.get_transaction_types", new_callable=AsyncMock)
def test_list_transaction_types_success(mock_service, client):

    mock_service.return_value = [
        {
            "type_id": str(uuid4()),
            "code": "CREDIT",
            "name": "Credit",
            "is_credit": True
        }
    ]

    response = client.get("/transactions/types")

    assert response.status_code == 200
    assert len(response.json()) == 1

def test_list_transaction_types_forbidden():

    app = FastAPI()
    app.include_router(router)

    from src.transaction.dependencies import get_current_user

    def employee_user():
        return CurrentUser(
            id=str(uuid4()),
            email="emp@test.com",
            roles=["EMPLOYEE"]
        )

    app.dependency_overrides[get_current_user] = employee_user

    client = TestClient(app)

    response = client.get("/transactions/types")

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /transactions
# ---------------------------------------------------------------------------

# Ensures list transaction endpoint returns paginated result
@patch("src.transaction.routes.get_transactions", new_callable=AsyncMock)
def test_list_transactions_success(mock_service, client):

    mock_service.return_value = {
        "page": 1,
        "limit": 10,
        "total": 1,
        "transactions": []
    }

    response = client.get(
        "/transactions",
        params={"wallet_id": str(uuid4()), "page": 1, "limit": 10}
    )

    assert response.status_code == 200
    assert response.json()["page"] == 1


# Ensures missing wallet_id query param returns 422
def test_list_transactions_missing_wallet_id(client):

    response = client.get("/transactions")

    assert response.status_code == 422

# Ensures limit above allowed max returns 422
def test_list_transactions_invalid_limit(client):

    response = client.get(
        "/transactions",
        params={"wallet_id": str(uuid4()), "limit": 200}
    )

    assert response.status_code == 422

# ---------------------------------------------------------------------------
# GET /transactions/{transaction_id}
# ---------------------------------------------------------------------------

# Ensures get transaction by ID returns correct structure
@patch("src.transaction.routes.get_transaction_by_id", new_callable=AsyncMock)
def test_get_transaction_by_id_success(mock_service, client):

    txn_id = str(uuid4())
    user_id = str(uuid4())

    mock_service.return_value = {
        "transaction_id": txn_id,
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
        "transaction_at": datetime.utcnow(),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "created_by": user_id,
        "updated_by": user_id,
    }

    response = client.get(f"/transactions/{txn_id}")

    assert response.status_code == 200
    assert response.json()["transaction_id"] == txn_id

from fastapi import HTTPException

@patch("src.transaction.routes.get_transaction_by_id", new_callable=AsyncMock)
def test_get_transaction_not_found(mock_service, client):

    mock_service.side_effect = HTTPException(status_code=404, detail="Not found")

    response = client.get(f"/transactions/{uuid4()}")

    assert response.status_code == 404