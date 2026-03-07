import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db, connect_with_retry
from src.wallet.routes import router as wallet_router
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.common.dependencies import close_auth_client
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

    try:
        await connect_redis()
        print("Wallet Service: 💚 Redis Connected")
    except Exception as e:
        print(f"Wallet Service: 💔 Redis Disconnected ({e}) — caching disabled")

    yield

    await close_auth_client()
    await disconnect_redis()
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

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top,https://www.aabhar.top").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], # Best practice: list specific methods if possible
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(wallet_router, prefix="/v1")