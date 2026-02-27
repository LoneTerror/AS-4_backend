from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError

from src.prisma.client import db
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)
from . import router as rewards_router

# --- IMPORT LOGGER ---
from src.core.logger import logger

app = FastAPI(
    title="Reward Microservice",
    description="API for managing the reward catalog and point redemptions.",
    version="1.0.0",
    root_path="/rewards"
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
)

# ── CORS must be registered FIRST so OPTIONS preflights are handled
#    before any other middleware or route matching runs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Request-ID",
        "X-Correlation-ID",
    ],
    expose_headers=[
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    ],
)

# ── Rate limiting + exception handlers
app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

# ── Routers
app.include_router(rewards_router.router)


@app.on_event("startup")
async def startup():
    logger.info("Initializing Reward Microservice...")
    try:
        if not db.is_connected():
            await db.connect()
            logger.info("Rewards Service: 🟢 Database Connected Successfully")
    except Exception as e:
        # If DB fails to connect on boot, log it as critical so we know immediately
        logger.critical(f"Rewards Service: 🔴 Database Connection Failed: {str(e)}", exc_info=True)


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down Reward Microservice...")
    try:
        if db.is_connected():
            await db.disconnect()
            logger.info("Rewards Service: 🔴 Database Disconnected Successfully")
    except Exception as e:
        logger.error(f"Rewards Service: Error during database disconnection: {str(e)}", exc_info=True)


@app.get("/")
@app.get("/health")
def health_check():
    # Using debug so health checks don't spam the info/production logs
    logger.debug("Health check endpoint pinged.")
    return {
        "service": "Reward Microservice",
        "status": "System Operational",
        "version": "0.1.0",
        "database": "Connected" if db.is_connected() else "Disconnected",
    }