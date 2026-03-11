import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError
from contextlib import asynccontextmanager

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
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
    prisma_unique_violation_handler
)
from . import router as rewards_router
from src.core.logger import logger
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    # ─── Employee & Manager Accessible ───────────────────────────────────────
    "GET:/catalog":                     ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/categories":                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/history":                     ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/history/me":                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/redeem":                     ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    
    # ─── Admin Only ────────────────────────────────────────────────────────
    "POST:/catalog":                    ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/catalog/{catalog_id}":      ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/catalog/{catalog_id}/stock":["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/categories":                 ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/categories/{category_id}":  ["SUPER_ADMIN", "HR_ADMIN"],
}

# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-rewards"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Reward Microservice...")
    await connect_with_retry()
    logger.info("Rewards Service: 🟢 Database Connected Successfully")

    try:
        await connect_redis()
        logger.info("Rewards Service: ☑️ Redis Connected")
    except Exception as e:
        logger.warning("Rewards Service: Redis unavailable (%s) — notifications will not be queued in real-time", e)

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
    )

    yield

    logger.info("Shutting down Reward Microservice...")
    await disconnect_redis()
    await db.disconnect()
    logger.info("Rewards Service: 🔴 Database Disconnected Successfully")


app = FastAPI(
    title="Reward Microservice",
    description="API for managing the reward catalog and point redemptions.",
    version="1.0.0",
    root_path="/v1/rewards", 
    openapi_url="/openapi.json", 
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/health", tags=["System"])
async def health_check():
    logger.debug("Health check endpoint pinged.")
    return {
        "service": "Reward Microservice",
        "status": "System Operational",
        "version": "1.0.0",
        "database": "Connected" if db.is_connected() else "Disconnected",
    }

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(UniqueViolationError,prisma_unique_violation_handler)

app.include_router(rewards_router.router)

# ==========================================
# Instrument FastAPI
# ==========================================
# Automatically trace HTTP requests, but ignore noisy health and docs endpoints
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json,/redoc"
)
# ==========================================