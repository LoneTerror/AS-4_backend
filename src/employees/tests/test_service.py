import pytest
from unittest.mock import AsyncMock, patch
from src.employees import service
from src.employees.service import list_employees
from src.employees.tests.conftest import make_employee_row

@pytest.mark.asyncio
async def test_list_employees_success():
    # Setup
    with patch.object(service.db.employees, "find_many", AsyncMock(return_value=[make_employee_row()])), \
         patch.object(service.db.employees, "count", AsyncMock(return_value=1)):
        
        # Execute
        result = await list_employees(page=1, limit=20)
        
        # Assert
        assert len(result.data) == 1
        assert result.data[0].username == "testuser"
        assert result.pagination.total == 1
        service.db.employees.find_many.assert_called_once()
        service.db.employees.count.assert_called_once()
