from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db,connect_with_retry
from src.wallet.routes import router as wallet_router
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Wallet Service: 🟢 Database Connected")
    yield
    await db.disconnect()
    print("Wallet Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Wallet Service",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    root_path="/wallet",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan
)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Wallet Service"}

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Wallet Service"}

# Router
app.include_router(wallet_router, prefix="/v1")
