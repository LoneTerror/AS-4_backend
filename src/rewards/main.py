import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware # Optional: remove import if no longer used anywhere
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
    "GET:/v1/rewards/catalog":                      ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/rewards/categories":                   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/rewards/history":                      ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/rewards/history/me":                   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/rewards/redeem":                      ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/rewards/catalog":                     ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/rewards/catalog/{catalog_id}":       ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/rewards/catalog/{catalog_id}/stock": ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/rewards/categories":                  ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/rewards/categories/{category_id}":   ["SUPER_ADMIN", "HR_ADMIN"],
}
# ── Rewards Service ───────────────────────────────────────────────────────────
ROUTE_TITLES = {
    "GET:/v1/rewards/catalog":                        "Browse Rewards Catalog",
    "GET:/v1/rewards/categories":                     "List Reward Categories",
    "GET:/v1/rewards/history":                        "View All Redemption History",
    "GET:/v1/rewards/history/me":                     "View My Redemption History",
    "POST:/v1/rewards/redeem":                        "Redeem Reward",
    "POST:/v1/rewards/catalog":                       "Add Catalog Item",
    "PATCH:/v1/rewards/catalog/{catalog_id}":         "Update Catalog Item",
    "PATCH:/v1/rewards/catalog/{catalog_id}/stock":   "Update Catalog Item Stock",
    "POST:/v1/rewards/categories":                    "Create Reward Category",
    "PATCH:/v1/rewards/categories/{category_id}":     "Update Reward Category",
}

resource = Resource.create({"service.name": "rnr-rewards"})
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter()
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)


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
        route_titles=ROUTE_TITLES,
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

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(UniqueViolationError, prisma_unique_violation_handler)

app.include_router(rewards_router.router)

# ==========================================
# Instrument FastAPI
# ==========================================
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json,/redoc"
)
# ==========================================