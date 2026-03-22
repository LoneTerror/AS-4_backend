import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError

# Import your existing, unmodified middleware logic
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    prisma_unique_violation_handler,
    validation_exception_handler,
    generic_exception_handler
)

def initialize_cors_and_middleware(app: FastAPI):
    """
    Handles CORS for AWS ALB and attaches existing middleware/handlers.
    Keeps the original middleware.py untouched.
    """
    
    # 1. CORS Implementation (The 'Smart' gatekeeper for the ALB)
    # Pulls from your K8s Secret: "https://aabhar.top,http://localhost:3000"
    origins_raw = os.getenv("FRONTEND_CORS_ORIGINS", "https://aabhar.top")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Attach your existing Rate Limiting logic
    app.middleware("http")(request_rate_limit_middleware)

    # 3. Attach your existing Global Exception Handlers
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(UniqueViolationError, prisma_unique_violation_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)