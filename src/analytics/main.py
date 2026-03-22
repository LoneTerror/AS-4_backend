"""
src/analytics/main.py
──────────────────────
Analytics Service.

Changes vs original:
1. Removed: CORSMiddleware and related origin logic.
2. Analytics owns ZERO tables — all data comes via internal HTTP.
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.analytics.reward_consumer import reward_redeemed_consumer_loop
from src.analytics.router import router as analytics_router
from src.common import internal_client
from src.common.dependencies import close_auth_client
from src.common.middleware import (
    generic_exception_handler,
    http_exception_handler,
    prisma_unique_violation_handler,
    request_rate_limit_middleware,
    validation_exception_handler,
)
from src.common.cors_setup import initialize_cors_and_middleware
from src.common.route_registry import register_app_routes
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import connect_with_retry, db

# --- OpenTelemetry Configuration ---
resource      = Resource.create({"service.name": "rnr-analytics"})
provider      = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter()
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

ROLE_OVERRIDES = {
    "GET:/v1/analytics/dashboard/leaderboard":           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/recent-reviews":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/platform-stats":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/teams":                 ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/teams/{department_id}": ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/participation":         ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/recognition-trend":     ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/recognition/teams":     ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/recognition/users":     ["SUPER_ADMIN", "HR_ADMIN"],
}
ROUTE_TITLES = {
    "GET:/v1/analytics/dashboard/leaderboard":           "View Leaderboard",
    "GET:/v1/analytics/dashboard/recent-reviews":        "View Recent Reviews",
    "GET:/v1/analytics/dashboard/platform-stats":        "View Platform Statistics",
    "GET:/v1/analytics/dashboard/teams":                 "View All Teams Overview",
    "GET:/v1/analytics/dashboard/teams/{department_id}": "View Team Details",
    "GET:/v1/analytics/dashboard/participation":         "View Participation Stats",
    "GET:/v1/analytics/dashboard/recognition-trend":     "View Recognition Trends",
    "GET:/v1/analytics/dashboard/recognition/teams":     "View Team Recognition",
    "GET:/v1/analytics/dashboard/recognition/users":     "View User Recognition",
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Analytics needs DB for team-report department lookups
    await connect_with_retry()
    print("Analytics Service: 🟢 Database Connected")

    shutdown_event = asyncio.Event()
    consumer_task  = None

    try:
        await connect_redis()
        print("Analytics Service: ☑️  Redis Connected")
        consumer_task = asyncio.create_task(
            reward_redeemed_consumer_loop(shutdown_event)
        )
    except Exception as exc:
        print(f"Analytics Service: ⚠️  Redis unavailable ({exc}) — caching disabled")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES,
    )

    yield

    # Cleanup
    shutdown_event.set()
    if consumer_task:
        await consumer_task

    await internal_client.close()
    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Analytics Service: 🔴 Disconnected")


app = FastAPI(
    title="Analytics Service",
    description="Dashboard analytics — reads from owning services via internal HTTP",
    version="1.0.0",
    root_path="/v1/analytics",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

initialize_cors_and_middleware(app)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Analytics Service"}


# Middleware & Exception Handlers
app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception,               generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException,           http_exception_handler)
app.add_exception_handler(UniqueViolationError,    prisma_unique_violation_handler)

app.include_router(analytics_router, prefix="/dashboard", tags=["Dashboard"])

# Instrumentation
FastAPIInstrumentor.instrument_app(
    app, excluded_urls="health,/docs,/openapi.json,/redoc"
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.analytics.main:app", host="0.0.0.0", port=8008, reload=True)