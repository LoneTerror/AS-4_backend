from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from src.prisma.client import db
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)
from . import router as rewards_router


app = FastAPI(
    title="Reward Microservice",
    description="API for managing the reward catalog and point redemptions.",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
)
app.middleware("http")(request_rate_limit_middleware)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)
app.include_router(rewards_router.router)

@app.on_event("startup")
async def startup():
    if not db.is_connected():
        await db.connect()
        print("Rewards Service: 🟢 Database Connected")

@app.on_event("shutdown")
async def shutdown():
    if db.is_connected():
        await db.disconnect()
        print("Rewards Service: 🔴 Database Disconnected")

@app.get("/")
@app.get("/health")
def health_check():
    return {
        "service": "Reward Microservice",
        "status": "System Operational",
        "version": "0.1.0",
        "database": "Connected" if db.is_connected() else "Disconnected"
    }