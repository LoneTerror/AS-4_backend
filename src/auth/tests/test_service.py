import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from src.auth import service
from src.auth.service import authenticate_user

@pytest.mark.asyncio
async def test_authenticate_user_success(sample_user):
    # Setup
    with patch.object(service.db.employees, "find_first", AsyncMock(return_value=sample_user)), \
         patch.object(service.db.refresh_tokens, "create", AsyncMock()):
        
        # Execute
        result = await authenticate_user("testuser", "correct_pass")
        
        # Assert
        assert result["access_token"] == "access_token"
        assert result["employee"]["username"] == "testuser"
        service.db.employees.find_first.assert_called_once()

@pytest.mark.asyncio
async def test_authenticate_user_not_found():
    # Setup
    with patch.object(service.db.employees, "find_first", AsyncMock(return_value=None)):
        
        # Execute & Assert
        with pytest.raises(HTTPException) as exc:
            await authenticate_user("ghost", "pass")
        
        assert exc.value.status_code == 401
        assert "Invalid credentials" in exc.value.detail

@pytest.mark.asyncio
async def test_authenticate_user_wrong_password(mock_sec, sample_user):
    # Setup
    mock_sec.verify_password.return_value = False
    with patch.object(service.db.employees, "find_first", AsyncMock(return_value=sample_user)):
        
        # Execute & Assert
        with pytest.raises(HTTPException) as exc:
            await authenticate_user("testuser", "wrong_pass")
        
        assert exc.value.status_code == 401
        assert "Invalid credentials" in exc.value.detail
