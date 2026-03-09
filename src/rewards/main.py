from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db, connect_with_retry
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Reward Microservice...")
    await connect_with_retry()
    logger.info("Rewards Service: 🟢 Database Connected Successfully")

    try:
        await connect_redis()
        logger.info("Rewards Service: 🔴 Redis Connected")
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
    root_path="/rewards",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(rewards_router.router)