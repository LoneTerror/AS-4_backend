"""
src/wallet/main.py  — Wallet Service entry point.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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

import logging
logger = logging.getLogger(__name__)

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

cors_origins_str     = os.getenv("FRONTEND_CORS_ORIGINS", "")
allowed_origins_list = [o.strip() for o in cors_origins_str.split(",") if o.strip()]


def _make_consumer_task(
    loop_fn,
    shutdown_event: asyncio.Event,
    name: str,
    consumer_tasks: list,
) -> asyncio.Task:
    """
    Create a consumer task with a done-callback that:
    - Logs any unhandled exception so silent crashes are visible
    - Auto-restarts the consumer after a 3-second delay if it crashes
      (unless shutdown is in progress)
    This prevents the "works only after restart" symptom caused by the
    task dying silently and only recovering via _recover_pending on next boot.
    """
    task = asyncio.create_task(loop_fn(shutdown_event), name=name)

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error("Consumer task '%s' crashed: %s — restarting in 3s", name, exc)
            if not shutdown_event.is_set():
                async def _restart():
                    await asyncio.sleep(3)
                    if not shutdown_event.is_set():
                        new_task = _make_consumer_task(loop_fn, shutdown_event, name, consumer_tasks)
                        # Replace the dead task reference in the shared list
                        for i, old in enumerate(consumer_tasks):
                            if old is t:
                                consumer_tasks[i] = new_task
                                break
                        else:
                            consumer_tasks.append(new_task)
                        logger.info("Consumer task '%s' restarted", name)
                asyncio.ensure_future(_restart())
        else:
            if not shutdown_event.is_set():
                logger.warning("Consumer task '%s' exited cleanly without shutdown signal", name)

    task.add_done_callback(_on_done)
    return task


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Wallet Service: 🟢 Database Connected")

    _shutdown      = asyncio.Event()
    consumer_tasks = []

    try:
        await connect_redis()
        print("Wallet Service: ☑️  Redis Connected")

        consumer_tasks.extend([
            _make_consumer_task(employee_created_consumer_loop, _shutdown, "employee_created_consumer", consumer_tasks),
            _make_consumer_task(review_created_consumer_loop,   _shutdown, "review_created_consumer",   consumer_tasks),
            _make_consumer_task(reward_redeemed_consumer_loop,  _shutdown, "reward_redeemed_consumer",  consumer_tasks),
        ])

        # Yield to the event loop so all three consumer tasks actually start
        # running before lifespan continues. Without this, tasks are scheduled
        # but not yet executing — their first xreadgroup call hasn't happened yet.
        await asyncio.sleep(0)

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


# Deprecated — returns 410 Gone so Recognition service callers get a clear signal
@app.post("/credit-from-review", include_in_schema=False)
async def credit_from_review_deprecated():
    return JSONResponse(status_code=410, content={
        "detail": "Deprecated. Use the review.created Redis Stream event instead."
    })


app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception,              generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException,          http_exception_handler)
app.add_exception_handler(UniqueViolationError,   prisma_unique_violation_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.include_router(wallet_router)
# ↓ NO prefix here — routes are already written as /internal/wallets/...
app.include_router(internal_router)

FastAPIInstrumentor.instrument_app(
    app, excluded_urls="health,docs,openapi.json,redoc,internal"
)