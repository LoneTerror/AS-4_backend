import uuid
import time
from collections import defaultdict
from datetime import datetime, timezone
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError
from starlette import status
from typing import cast

from src.core.logger import logger

# ==========================================================
# CONFIG
# ==========================================================
RATE_LIMIT     = 1000
WINDOW_SECONDS = 3600

requests_store: defaultdict[str, list[float]] = defaultdict(list)

# Periodic cleanup — purge IPs not seen in the last hour every 10 minutes.
# Prevents requests_store growing unbounded in long-running processes
# where many unique IPs accumulate over time.
_CLEANUP_INTERVAL_SECONDS = 600
_last_cleanup = time.time()


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
        503: "SERVICE_UNAVAILABLE",
    }
    return mapping.get(status_code, "INTERNAL_ERROR")


# ==========================================================
# GLOBAL ERROR HANDLERS
# ==========================================================
async def http_exception_handler(request: Request, exc: Exception):
    specific_exc = cast(HTTPException, exc)
    
    request_id = getattr(request.state, "request_id", "unknown")

    if specific_exc.status_code >= 500:
        logger.error(f"[{request_id}] HTTP {specific_exc.status_code} at {request.url.path}: {specific_exc.detail}")
    else:
        logger.warning(f"[{request_id}] HTTP {specific_exc.status_code} at {request.url.path}: {specific_exc.detail}")

    return JSONResponse(
        status_code=specific_exc.status_code,
        content={
            "error": {
                "code":       map_status_to_error_code(specific_exc.status_code),
                "message":    specific_exc.detail,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "path":       request.url.path,
                "request_id": request_id,
            }
        },
    )


async def prisma_unique_violation_handler(request: Request, exc: Exception):
    # Cast the generic exception to the specific one for type safety and autocomplete
    specific_exc = cast(UniqueViolationError, exc)

    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning(f"[{request_id}] Unique Constraint Violation at {request.url.path}: {str(specific_exc)}")

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code":       "CONFLICT",
                "message":    "A record with this unique identifier already exists.",
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "path":       request.url.path,
                "request_id": request_id,
            }
        },
    )


async def validation_exception_handler(request: Request, exc: Exception):
    specific_exc = cast(RequestValidationError, exc)

    request_id = getattr(request.state, "request_id", "unknown")

    formatted_errors = {}
    for err in specific_exc.errors():
        field = err["loc"][-1]
        formatted_errors.setdefault(field, []).append(err["msg"])

    logger.warning(f"[{request_id}] Validation Error at {request.url.path}: {formatted_errors}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code":       "VALIDATION_ERROR",
                "message":    "Request validation failed",
                "details":    formatted_errors,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "path":       request.url.path,
                "request_id": request_id,
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"[{request_id}] Unhandled Server Error at {request.url.path}: {str(exc)}",
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code":       "INTERNAL_ERROR",
                "message":    "An unexpected error occurred",
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "path":       request.url.path,
                "request_id": request_id,
            }
        },
    )


# ==========================================================
# MAIN MIDDLEWARE
# ==========================================================
async def request_rate_limit_middleware(request: Request, call_next):
    global _last_cleanup
    start_time = time.time()

    # 1. Request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    # Extract true client IP from proxy headers, fallback to socket host, then null-check
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"
    logger.info(f"[{request_id}] Incoming {request.method} {request.url.path} from IP: {client_ip}")

    now          = time.time()
    window_start = now - WINDOW_SECONDS

    # 2. Periodic cleanup — purge stale IPs to prevent memory leak.
    #    Runs at most once every _CLEANUP_INTERVAL_SECONDS regardless of traffic.
    if now - _last_cleanup > _CLEANUP_INTERVAL_SECONDS:
        stale_ips = [
            ip for ip, timestamps in requests_store.items()
            if not timestamps or timestamps[-1] < window_start
        ]
        for ip in stale_ips:
            del requests_store[ip]
        _last_cleanup = now
        if stale_ips:
            logger.debug("Rate limit store: purged %d stale IP(s)", len(stale_ips))

    # 3. Slide the window — drop timestamps outside the current window
    requests_store[client_ip] = [
        ts for ts in requests_store[client_ip] if ts > window_start
    ]

    # 4. Rate limit check
    if len(requests_store[client_ip]) >= RATE_LIMIT:
        logger.warning(f"[{request_id}] Rate limit exceeded for IP: {client_ip}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )

    requests_store[client_ip].append(now)

    try:
        response = await call_next(request)
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"[{request_id}] Request failed after {process_time:.4f}s")
        raise e

    process_time = time.time() - start_time
    logger.info(
        f"[{request_id}] Completed {request.method} {request.url.path} "
        f"- Status: {response.status_code} - Took: {process_time:.4f}s"
    )

    # 5. Attach rate limit headers
    remaining  = RATE_LIMIT - len(requests_store[client_ip])
    reset_time = int(requests_store[client_ip][0] + WINDOW_SECONDS)

    response.headers["X-Request-ID"]          = request_id
    response.headers["X-RateLimit-Limit"]     = str(RATE_LIMIT)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"]     = str(reset_time)

    return response