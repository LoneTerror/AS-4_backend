import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.digest.service import DigestService
from src.digest.schemas import WeeklyDigestData
from datetime import datetime, timezone

@pytest.mark.asyncio
async def test_send_digest_email_success(db, mock_sender):
    # Setup
    svc = DigestService(db, mock_sender)
    
    mock_data = MagicMock(spec=WeeklyDigestData)
    mock_data.total_recognitions = 5
    mock_data.week_start = datetime.now(timezone.utc)
    
    # We must patch the function in the module where service.py imports it from
    with patch("src.digest.service.fetch_weekly_digest_data", AsyncMock(return_value=mock_data)), \
         patch("src.digest.service.build_digest_html", MagicMock(return_value=("Subject", "HTML"))):
        
        # Execute
        result = await svc.send_digest_email(manager_email="mgr@test.com")
        
        # Assert
        assert result.success is True
        assert result.message == "Digest sent to mgr@test.com"
        mock_sender.send_notification_email.assert_called_once()

@pytest.mark.asyncio
async def test_send_digest_email_failure(db, mock_sender):
    # Setup
    svc = DigestService(db, mock_sender)
    
    with patch("src.digest.service.fetch_weekly_digest_data", AsyncMock(side_effect=Exception("DB Error"))):
        # Execute
        result = await svc.send_digest_email(manager_email="mgr@test.com")
        
        # Assert
        assert result.success is False
        assert "Failed" in result.message
