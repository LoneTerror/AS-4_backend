from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.recognition.router import router as recognition_router
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    print("Employee Service: 🟢 Database Connected")
    yield
    await db.disconnect()
    print("Employee Service: 🔴 Database Disconnected")

app = FastAPI(
    title="Recognition Service",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan
)

# Register middleware
app.middleware("http")(request_rate_limit_middleware)

# Register exception handlers
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Request-ID",
        "X-Correlation-ID",
    ],
    expose_headers=[
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ],
)

# Router
app.include_router(recognition_router, prefix="/v1", tags=["Recognition"])
