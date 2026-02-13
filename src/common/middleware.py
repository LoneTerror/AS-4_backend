"""
Common Middleware Module
Handles:
- Request ID generation
- Rate limiting
- Contract-compliant headers
"""

import uuid
import time
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette import status

# ==========================================================
# CONFIG
# ==========================================================
RATE_LIMIT = 1000
WINDOW_SECONDS = 3600  # 1 hour

requests_store = defaultdict(list)


# ==========================================================
# ERROR CODE MAPPING
# ==========================================================
def map_status_to_error_code(status_code: int) -> str:
    mapping = {
        400: "INVALID_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "RESOURCE_NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE"
    }
    return mapping.get(status_code, "INTERNAL_ERROR")


# ==========================================================
# GLOBAL ERROR HANDLERS
# ==========================================================
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": map_status_to_error_code(exc.status_code),
                "message": exc.detail,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": request.url.path,
                "request_id": request_id
            }
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)

    formatted_errors = {}
    for err in exc.errors():
        field = err["loc"][-1]
        formatted_errors.setdefault(field, []).append(err["msg"])

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": formatted_errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": request.url.path,
                "request_id": request_id
            }
        }
    )


async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": request.url.path,
                "request_id": request_id
            }
        }
    )


# ==========================================================
# MAIN MIDDLEWARE
# ==========================================================
async def request_rate_limit_middleware(request: Request, call_next):

    # 1️⃣ Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    # 2️⃣ Rate limiting (in-memory)
    client_ip = request.client.host
    now = time.time()
    window_start = now - WINDOW_SECONDS

    requests_store[client_ip] = [
        ts for ts in requests_store[client_ip] if ts > window_start
    ]

    if len(requests_store[client_ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    requests_store[client_ip].append(now)

    response = await call_next(request)

    # 3️⃣ Attach headers
    remaining = RATE_LIMIT - len(requests_store[client_ip])
    reset_time = int(requests_store[client_ip][0] + WINDOW_SECONDS)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_time)

    return response
