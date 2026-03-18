import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request, HTTPException,status
from fastapi.exceptions import RequestValidationError
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
    prisma_unique_violation_handler,
    requests_store,
    RATE_LIMIT,
    WINDOW_SECONDS
)

@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    # FIX: Add the ID to headers so the middleware finds it
    request.headers = {"X-Request-ID": "test-request-id-123"}
    request.client = MagicMock()
    request.client.host = "127.0.0.1"
    request.method = "GET"
    request.url.path = "/test"
    
    request.state = MagicMock()
    request.state.request_id = "test-request-id-123"
    
    return request

@pytest.mark.asyncio
class TestMiddleware:

    def setup_method(self):
        """Clear the in-memory rate limit store before each test."""
        requests_store.clear()

    # ===========================================================================
    # 1. RATE LIMIT MIDDLEWARE
    # ===========================================================================
    async def test_rate_limit_pass(self, mock_request):
        call_next = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        call_next.return_value = mock_response

        response = await request_rate_limit_middleware(mock_request, call_next)
        
        # Now this will match because it's pulled from headers
        assert response.headers["X-Request-ID"] == "test-request-id-123"
        assert int(response.headers["X-RateLimit-Remaining"]) == RATE_LIMIT - 1
        call_next.assert_called_once()

    async def test_rate_limit_exceeded(self, mock_request):
        client_ip = "127.0.0.1"
        requests_store[client_ip] = [time.time()] * RATE_LIMIT
        
        call_next = AsyncMock()
        with pytest.raises(HTTPException) as exc:
            await request_rate_limit_middleware(mock_request, call_next)
        assert exc.value.status_code == 429

    # ===========================================================================
    # 2. EXCEPTION HANDLERS
    # ===========================================================================
    async def test_http_exception_handler_400(self, mock_request):
        exc = HTTPException(status_code=400, detail="Bad Data")
        response = await http_exception_handler(mock_request, exc)
        assert response.status_code == 400
        assert b"INVALID_REQUEST" in response.body

    async def test_validation_exception_handler(self, mock_request):
        mock_exc = MagicMock(spec=RequestValidationError)
        mock_exc.errors.return_value = [
            {"loc": ["body", "email"], "msg": "invalid", "type": "value_error"}
        ]
        
        response = await validation_exception_handler(mock_request, mock_exc)
        # Using UNPROCESSABLE_CONTENT to resolve DeprecationWarning
        # Import 'status' from starlette or fastapi
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT 
        assert b"VALIDATION_ERROR" in response.body

    async def test_prisma_unique_violation_handler(self, mock_request):
        response = await prisma_unique_violation_handler(mock_request, Exception("Duplicate"))
        assert response.status_code == 409

    async def test_generic_exception_handler(self, mock_request):
        response = await generic_exception_handler(mock_request, Exception("Boom"))
        assert response.status_code == 500