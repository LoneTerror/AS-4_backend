import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.wallet import service
from src.wallet.service import get_transaction_types

@pytest.mark.asyncio
async def test_get_transaction_types_miss_cache(admin_user):
    # Setup
    mock_type = MagicMock()
    mock_type.type_id = "type-1"
    mock_type.type_code = "CREDIT"
    mock_type.type_name = "Credit"
    mock_type.is_credit = True
    
    with patch.object(service.db.transaction_types, "find_many", AsyncMock(return_value=[mock_type])), \
         patch.object(service, "cache_get", AsyncMock(return_value=None)), \
         patch.object(service, "cache_set", AsyncMock()):
        
        # Execute
        result = await get_transaction_types(admin_user)
        
        # Assert
        assert len(result) == 1
        assert result[0]["code"] == "CREDIT"
        service.db.transaction_types.find_many.assert_called_once()
