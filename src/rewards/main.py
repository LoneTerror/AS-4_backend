import os
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing Reward Microservice...")
    await connect_with_retry()
    logger.info("Rewards Service: 🟢 Database Connected Successfully")

    try:
        await connect_redis()
        logger.info("Rewards Service: 💚 Redis Connected")
    except Exception as e:
        logger.warning("Rewards Service: 💔 Redis Disconnected (%s) — notifications will not be queued in real-time", e)

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

origins = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top").split(",")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(rewards_router.router)