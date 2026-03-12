import pytest
from unittest.mock import AsyncMock, MagicMock
from src.organization.service import list_departments

from uuid import uuid4

@pytest.mark.asyncio
async def test_list_departments_success(db):
    # Setup
    mock_dept = MagicMock()
    mock_dept.department_id = str(uuid4())
    mock_dept.department_name = "Engineering"
    mock_dept.department_code = "ENG"
    mock_dept.department_types = None
    
    db.departments.find_many = AsyncMock(return_value=[mock_dept])
    db.departments.count = AsyncMock(return_value=1)
    
    # Execute
    result = await list_departments(page=1, limit=20, is_active=True, search=None)
    
    # Assert
    assert len(result.data) == 1
    assert result.data[0].department_name == "Engineering"
    db.departments.find_many.assert_called_once()
    db.departments.count.assert_called_once()
