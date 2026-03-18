import logging
import os
import pytest
import uuid
from unittest.mock import MagicMock, patch
from src.core.logger import MaskingFormatter, ExactLevelFilter, setup_logger

class TestMaskingFormatter:
    @pytest.fixture
    def formatter(self):
        return MaskingFormatter("%(message)s")

    def test_mask_uuid(self, formatter):
        raw_uuid = "550e8400-e29b-41d4-a716-446655440000"
        record = logging.LogRecord("test", logging.INFO, "", 0, raw_uuid, None, None)
        assert formatter.format(record) == "550e8400-****-****-****-0000"

    def test_mask_email(self, formatter):
        email = "alex.dev@example.com"
        record = logging.LogRecord("test", logging.INFO, "", 0, f"User {email}", None, None)
        assert formatter.format(record) == "User a****@example.com"

    def test_mask_phone(self, formatter):
        phone = "+1-555-012-3456"
        record = logging.LogRecord("test", logging.INFO, "", 0, f"Call {phone}", None, None)
        assert formatter.format(record) == "Call +***-***-3456"

class TestLoggerFilters:
    def test_exact_level_filter(self):
        f = ExactLevelFilter(logging.DEBUG)
        assert f.filter(logging.LogRecord("t", logging.DEBUG, "", 0, "m", None, None)) is True
        assert f.filter(logging.LogRecord("t", logging.INFO, "", 0, "m", None, None)) is False

class TestLoggerSetup:
    def test_setup_logger_initialization(self):
        # 1. Use a unique name
        name = f"test_init_{uuid.uuid4().hex}"
        
        # 2. Force clean state: Remove if exists in manager
        test_logger = logging.getLogger(name)
        test_logger.handlers = [] 
        
        # 3. Run setup
        logger = setup_logger(name)
        
        # 4. Assert
        handler_names = [type(h).__name__ for h in logger.handlers]
        assert "RotatingFileHandler" in handler_names
        assert "StreamHandler" in handler_names
        assert len(logger.handlers) >= 4

    def test_log_directory_creation(self):
        name = f"test_dir_{uuid.uuid4().hex}"

        mock_logger = MagicMock(spec=logging.Logger)
        mock_logger.handlers = []  # ← replace hasHandlers mock with this

        with patch("logging.getLogger", return_value=mock_logger), \
            patch("os.makedirs") as mock_makedirs:
            setup_logger(name)
            mock_makedirs.assert_called_with("logs", exist_ok=True)