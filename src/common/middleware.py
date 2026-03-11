import uuid
import time
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError
from starlette import status

# --- IMPORT LOGGER ---
from src.core.logger import logger

# ==========================================================
# CONFIG
# ==========================================================
RATE_LIMIT = 1000
WINDOW_SECONDS = 3600  

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
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Log 5xx errors as actual errors, but 4xx as warnings (since 4xx is a client issue)
    if exc.status_code >= 500:
        logger.error(f"[{request_id}] HTTP {exc.status_code} at {request.url.path}: {exc.detail}")
    else:
        logger.warning(f"[{request_id}] HTTP {exc.status_code} at {request.url.path}: {exc.detail}")

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

async def prisma_unique_violation_handler(request: Request, exc: UniqueViolationError):
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Log the conflict
    logger.warning(f"[{request_id}] Unique Constraint Violation at {request.url.path}: {str(exc)}")

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "CONFLICT",
                "message": "A record with this unique identifier already exists.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": request.url.path,
                "request_id": request_id
            }
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "unknown")

    formatted_errors = {}
    for err in exc.errors():
        field = err["loc"][-1]
        formatted_errors.setdefault(field, []).append(err["msg"])

    logger.warning(f"[{request_id}] Validation Error at {request.url.path}: {formatted_errors}")

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
    request_id = getattr(request.state, "request_id", "unknown")

    # CRITICAL: This captures the raw stack trace of unexpected crashes (500s)
    logger.error(f"[{request_id}] Unhandled Server Error at {request.url.path}: {str(exc)}", exc_info=True)

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
    start_time = time.time()

    # 1. Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    client_ip = request.client.host
    logger.info(f"[{request_id}] Incoming {request.method} {request.url.path} from IP: {client_ip}")

    # 2. Rate limiting (in-memory)
    now = time.time()
    window_start = now - WINDOW_SECONDS

    requests_store[client_ip] = [
        ts for ts in requests_store[client_ip] if ts > window_start
    ]

    if len(requests_store[client_ip]) >= RATE_LIMIT:
        logger.warning(f"[{request_id}] Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )

    requests_store[client_ip].append(now)

    try:
        response = await call_next(request)
    except Exception as e:
        # If an error happens during the request, we log the failure time
        process_time = time.time() - start_time
        logger.error(f"[{request_id}] Request failed after {process_time:.4f}s")
        raise e

    process_time = time.time() - start_time
    logger.info(f"[{request_id}] Completed {request.method} {request.url.path} - Status: {response.status_code} - Took: {process_time:.4f}s")

    # 3. Attach headers
    remaining = RATE_LIMIT - len(requests_store[client_ip])
    reset_time = int(requests_store[client_ip][0] + WINDOW_SECONDS)

    response.headers["X-Request-ID"] = request_id
    response.headers["X-RateLimit-Limit"] = str(RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset_time)

    return response