import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from src.notifications.service import NotificationService
from src.notifications.schemas import NotificationType
from uuid import uuid4

@pytest.mark.asyncio
async def test_create_notification_success(db):
    # Setup
    mock_record = MagicMock()
    mock_record.notification_id = "notif-1"
    mock_record.model_dump.return_value = {"notification_id": "notif-1"}
    
    # Check what is in sys.modules
    print(f"DEBUG_TEST: sys.modules['src.prisma.client'].db is {sys.modules['src.prisma.client'].db}")
    
    svc = NotificationService(db, redis=None)
    
    # Force it on the instance directly
    svc._db.notifications.create = AsyncMock(return_value=mock_record)
    
    # Execute
    result = await svc.create_notification(
        employee_id=str(uuid4()),
        title="Test Title",
        message="Test Message",
        type=NotificationType.SYSTEM
    )
    
    # Assert
    assert result["notification_id"] == "notif-1"
    svc._db.notifications.create.assert_called_once()
