from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import os

# --- OpenTelemetry Imports ---
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# -----------------------------

from src.prisma.client import db, connect_with_retry
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.common.dependencies import close_auth_client
from src.analytics.router import router as analytics_router
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    "GET:/v1/analytics/dashboard/leaderboard":              ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/recent-reviews":           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/teams":                    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/teams/{department_id}":    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/platform-stats":           ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/analytics/dashboard/participation":            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/recognition-trend":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/recognition/teams":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/analytics/dashboard/recognition/users":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
}

ROUTE_TITLES = {
    "GET:/v1/analytics/dashboard/leaderboard":              "View Leaderboard",
    "GET:/v1/analytics/dashboard/recent-reviews":           "View Recent Reviews",
    "GET:/v1/analytics/dashboard/teams":                    "View All Teams Overview",
    "GET:/v1/analytics/dashboard/teams/{department_id}":    "View Team Details",
    "GET:/v1/analytics/dashboard/platform-stats":           "View Platform Statistics",
    "GET:/v1/analytics/dashboard/participation":            "View Participation Stats",
    "GET:/v1/analytics/dashboard/recognition-trend":        "View Recognition Trends",
    "GET:/v1/analytics/dashboard/recognition/teams":        "View Team Recognition",
    "GET:/v1/analytics/dashboard/recognition/users":        "View User Recognition",
}
# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-analytics"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Analytics Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Analytics Service: 🟢 Redis Connected")
    except Exception as e:
        print(f"Analytics Service: ⚠️  Redis unavailable ({e}) — caching disabled")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES,
    )

    yield

    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Analytics Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Analytics Service",
    description="Dashboard summary and analytics endpoints",
    version="1.0.0",
    root_path="/v1/analytics",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Analytics Service"}


app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.include_router(analytics_router, prefix="/dashboard", tags=["Dashboard"])

# ==========================================
# Instrument FastAPI
# ==========================================
# Automatically trace HTTP requests, but ignore noisy health and docs endpoints
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json,/redoc"
)
# ==========================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.analytics.main:app", host="0.0.0.0", port=8008, reload=True)