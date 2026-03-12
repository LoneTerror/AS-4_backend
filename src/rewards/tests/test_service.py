from datetime import datetime, timezone
import pytest
import uuid
from fastapi import HTTPException
from unittest.mock import MagicMock, AsyncMock
from src.rewards.service import RewardService
from src.rewards.schemas import CreateCategoryRequest, GrantRewardRequest, AddStockRequest

# Generate some valid UUIDs to satisfy Pydantic's strict UUID4 validation
VALID_WALLET_UUID = str(uuid.uuid4())
VALID_CATALOG_UUID = str(uuid.uuid4())

# ---------------------------------------------------------
# Category Management Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_create_category_success(mock_db, mocker):
    # Initialize service with the mock DB
    service = RewardService(mock_db)
    
    # FIX 1: Use AsyncMock because _log_change is an async function
    mocker.patch.object(service, '_log_change', new_callable=AsyncMock)
    
    # Mock DB: No existing category found
    mock_db.reward_categories.find_unique.return_value = None
    
    # Mock DB: Create returns the new category
    mock_created = MagicMock()
    mock_created.category_id = VALID_CATALOG_UUID
    mock_created.category_name = "Gift Cards"
    mock_created.category_code = "CAT-GIFT"
    mock_db.reward_categories.create.return_value = mock_created

    request_data = CreateCategoryRequest(
        category_name="Gift Cards",
        category_code="CAT-GIFT"
    )
    
    # Dummy request for IP/User-Agent extraction in _log_change
    dummy_req = MagicMock()
    dummy_req.client.host = "127.0.0.1"
    dummy_req.headers.get.return_value = "pytest"

    # Execute
    result = await service.create_category(request_data, "admin-123", dummy_req)

    # Assertions
    assert result == mock_created
    mock_db.reward_categories.create.assert_called_once()
    service._log_change.assert_called_once()


@pytest.mark.asyncio
async def test_create_category_conflict(mock_db):
    service = RewardService(mock_db)
    
    # Mock DB: Category already exists
    mock_db.reward_categories.find_unique.return_value = MagicMock()

    request_data = CreateCategoryRequest(
        category_name="Gift Cards",
        category_code="CAT-GIFT"
    )

    with pytest.raises(HTTPException) as exc:
        await service.create_category(request_data, "admin-123", MagicMock())
    
    assert exc.value.status_code == 400
    assert "already exists" in exc.value.detail


# ---------------------------------------------------------
# Redemption & Inventory Tests (grant_reward)
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_grant_reward_out_of_stock(mock_db):
    service = RewardService(mock_db)
    
    # Mock Catalog Item (Out of stock)
    mock_item = MagicMock()
    mock_item.is_active = True
    mock_item.available_stock = 0
    mock_db.reward_catalog.find_unique.return_value = mock_item

    # FIX 2: Use valid UUID strings
    request_data = GrantRewardRequest(
        wallet_id=VALID_WALLET_UUID,
        catalog_id=VALID_CATALOG_UUID,
        points=100
    )

    with pytest.raises(HTTPException) as exc:
        await service.grant_reward(request_data, "emp-123")
    
    assert exc.value.status_code == 400
    assert "Out of stock" in exc.value.detail


@pytest.mark.asyncio
async def test_grant_reward_success(mock_db, mocker):
    service = RewardService(mock_db)
    
    # Mock Notification Service specifically on the instance
    mock_notif = AsyncMock()
    mocker.patch.object(service, '_notif', mock_notif)
    
    # 1. Setup Request with valid UUIDs
    request_data = GrantRewardRequest(
        wallet_id=VALID_WALLET_UUID,
        catalog_id=VALID_CATALOG_UUID,
        points=100,
        comment="Great job!"
    )

    # 2. Mock Pre-flight Checks
    mock_item = MagicMock(is_active=True, available_stock=10, min_points=50, max_points=150, reward_name="Coffee")
    mock_db.reward_catalog.find_unique.return_value = mock_item
    
    mock_wallet = MagicMock(available_points=500, employee_id="emp-123")
    mock_db.wallets.find_unique.return_value = mock_wallet
    
    # Mock Lookup tables (_get_sys_id wrapper)
    async def mock_sys_id(table, code_field, code_value):
        return "sys-id-123"
    mocker.patch.object(service, '_get_sys_id', side_effect=mock_sys_id)

    # 3. FIX: Properly mock the async context manager (`async with self.db.tx() as transaction:`)
    # First, create a mock for the inner 'transaction' database object
    transaction_mock = AsyncMock()
    transaction_mock.wallets.update = AsyncMock()
    transaction_mock.reward_catalog.update = AsyncMock(return_value=MagicMock(available_stock=9))
    transaction_mock.transactions.create = AsyncMock()
    transaction_mock.reward_history.create = AsyncMock(return_value=MagicMock(history_id="h-1"))
    transaction_mock.reward_catalog.update.return_value = MagicMock(available_stock=9)
    transaction_mock.reward_history.create.return_value = MagicMock(history_id="hist-1", points=100, granted_at="2026-03-02")

    # Second, create the async context manager
    tx_context_manager = AsyncMock()
    tx_context_manager.__aenter__.return_value = transaction_mock
    tx_context_manager.__aexit__.return_value = None

    # THE FIX: Completely overwrite mock_db.tx with a synchronous MagicMock
    mock_db.tx = MagicMock(return_value=tx_context_manager)

    # 4. Execute
    response = await service.grant_reward(request_data, "admin-123")

    # 5. Assertions
    assert response["status"] == "COMPLETED"
    assert response["new_stock_level"] == 9
    
    # Verify Wallet deduction was called in the transaction block
    transaction_mock.wallets.update.assert_called_once()
    wallet_update_args = transaction_mock.wallets.update.call_args[1]["data"]
    assert wallet_update_args["available_points"]["decrement"] == 100
    
    # Verify notification was triggered
    mock_notif.create_notification.assert_called_once()

@pytest.mark.asyncio
async def test_get_catalog_pagination(mock_db):
    service = RewardService(mock_db)
    
    # Fully populate mock data to satisfy Pydantic's RewardItemResponse
    mock_item_1 = MagicMock(
        catalog_id=VALID_CATALOG_UUID,
        reward_name="Item 1",
        reward_code="ITM-1",
        description="A great reward",
        default_points=100,
        min_points=100,
        max_points=100,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        available_stock=15,
        # Fully populate the nested category mock to satisfy MinimalCategoryInfo
        reward_categories=MagicMock(
            category_id=str(uuid.uuid4()), 
            category_name="Tech", 
            category_code="CAT-TECH"
        )
    )
    
    mock_item_2 = MagicMock(
        catalog_id=str(uuid.uuid4()),
        reward_name="Item 2",
        reward_code="ITM-2",
        description="Another reward",
        default_points=50,
        min_points=50,
        max_points=50,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        available_stock=0, # Maps to "Out of Stock"
        reward_categories=None # Testing null safety
    )
    
    # Mock the count (say we have 12 items total in the DB)
    mock_db.reward_catalog.count.return_value = 12
    # Mock the find_many to return our 2 items for this specific "page"
    mock_db.reward_catalog.find_many.return_value = [mock_item_1, mock_item_2]

    # Execute request for Page 2, Size 10
    response = await service.get_catalog(active_only=True, page=2, size=10)

    # Assertions
    assert len(response["data"]) == 2
    
    # Check data mapping and stock status logic
    assert response["data"][0].stock_status == "In Stock"
    assert response["data"][0].category.category_name == "Tech"
    
    assert response["data"][1].stock_status == "Out of Stock"
    assert response["data"][1].category is None

    # Check Pagination Math
    pagination = response["pagination"]
    assert pagination["current_page"] == 2
    assert pagination["per_page"] == 10
    assert pagination["total"] == 12
    assert pagination["total_pages"] == 2 # 12 items / 10 per page = 2 pages
    assert pagination["has_next"] is False # We are on the last page
    assert pagination["has_previous"] is True # There is a page 1


# ---------------------------------------------------------
# Inventory Management Tests
# ---------------------------------------------------------
@pytest.mark.asyncio
async def test_add_stock_success(mock_db, mocker):
    service = RewardService(mock_db)
    mocker.patch.object(service, '_log_change', new_callable=AsyncMock)

    # Mock finding the item
    mock_existing = MagicMock(available_stock=5)
    mock_db.reward_catalog.find_unique.return_value = mock_existing

    # Fully populate the updated item to satisfy RewardItemResponse
    mock_updated = MagicMock(
        catalog_id=VALID_CATALOG_UUID,
        reward_name="T-Shirt",
        reward_code="TSHIRT-01",
        description="Company Merch",
        default_points=20,
        min_points=20,
        max_points=20,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        available_stock=25, # 5 + 20
        reward_categories=None
    )
    mock_db.reward_catalog.update.return_value = mock_updated

    request_data = AddStockRequest(amount=20)
    dummy_req = MagicMock()

    # Execute
    response = await service.add_stock(VALID_CATALOG_UUID, request_data, "admin-123", dummy_req)

    # Assertions
    assert response.available_stock == 25
    assert response.stock_status == "In Stock"
    
    # Verify the atomic increment was passed to Prisma correctly
    mock_db.reward_catalog.update.assert_called_once()
    update_args = mock_db.reward_catalog.update.call_args[1]
    assert update_args["data"]["available_stock"]["increment"] == 20
    
    # Verify Audit log was called
    service._log_change.assert_called_once()