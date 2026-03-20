"""
src/wallet/main.py  — Wallet Service entry point.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
# CORSMiddleware import removed
from fastapi.responses import JSONResponse
from prisma.errors import UniqueViolationError

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.common.dependencies import close_auth_client
from src.common.middleware import (
    generic_exception_handler, http_exception_handler,
    prisma_unique_violation_handler, request_rate_limit_middleware,
    validation_exception_handler,
)
from src.common.route_registry import register_app_routes
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import connect_with_retry, db
from src.wallet.employee_consumer import employee_created_consumer_loop
from src.wallet.internal_router import router as internal_router
from src.wallet.review_consumer import review_created_consumer_loop
from src.wallet.reward_consumer import reward_redeemed_consumer_loop
from src.wallet.routes import router as wallet_router

# --- OpenTelemetry Configuration ---
resource      = Resource.create({"service.name": "rnr-wallet"})
provider      = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter()
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

ROLE_OVERRIDES = {
    "GET:/v1/wallets/employees/{employee_id}":       ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/wallets/{wallet_id}/balance":           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/wallets/{wallet_id}/points-summary":    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/wallets/transactions":                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/wallets/transactions/{transaction_id}": ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/wallets/transactions/types":            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/wallets/transactions":                 ["SUPER_ADMIN", "HR_ADMIN", "MANAGER"],
}
ROUTE_TITLES = {
    "GET:/v1/wallets/employees/{employee_id}":        "Get Employee Wallet",
    "GET:/v1/wallets/{wallet_id}/balance":            "Get Wallet Balance",
    "GET:/v1/wallets/{wallet_id}/points-summary":     "Get Points Summary",
    "GET:/v1/wallets/transactions":                   "List All Transactions",
    "GET:/v1/wallets/transactions/{transaction_id}":  "Get Transaction Details",
    "GET:/v1/wallets/transactions/types":             "List Transaction Types",
    "POST:/v1/wallets/transactions":                  "Create Transaction",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Wallet Service: 🟢 Database Connected")

    _shutdown      = asyncio.Event()
    consumer_tasks = []

    try:
        await connect_redis()
        print("Wallet Service: ☑️  Redis Connected")
        consumer_tasks = [
            asyncio.create_task(employee_created_consumer_loop(_shutdown), name="employee_created_consumer"),
            asyncio.create_task(review_created_consumer_loop(_shutdown),   name="review_created_consumer"),
            asyncio.create_task(reward_redeemed_consumer_loop(_shutdown),  name="reward_redeemed_consumer"),
        ]
        print("Wallet Service: 👂 Stream consumers started")
    except Exception as exc:
        print(f"Wallet Service: ⚠️  Redis unavailable ({exc}) — consumers disabled")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES,
    )

    yield

    _shutdown.set()
    for task in consumer_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    print("Wallet Service: 👂 Consumers stopped")

    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Wallet Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Wallet Service",
    version="1.0.0",
    root_path="/v1/wallets",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Wallet Service"}


# Deprecated route remains for signal consistency
@app.post("/credit-from-review", include_in_schema=False)
async def credit_from_review_deprecated():
    return JSONResponse(status_code=410, content={
        "detail": "Deprecated. Use the review.created Redis Stream event instead."
    })


# Middleware & Exception Handlers
app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception,               generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException,           http_exception_handler)
app.add_exception_handler(UniqueViolationError,    prisma_unique_violation_handler)

# CORS MIDDLEWARE REMOVED FROM HERE

app.include_router(wallet_router)
app.include_router(internal_router)

# Instrumentation
FastAPIInstrumentor.instrument_app(
    app, excluded_urls="health,docs,openapi.json,redoc,internal"
)