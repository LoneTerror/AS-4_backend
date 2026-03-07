import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Analytics Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Analytics Service: 💚 Redis Connected")
    except Exception as e:
        print(f"Analytics Service: 💔 Redis Disconnected ({e}) — caching disabled")

    yield

    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Analytics Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Analytics Service",
    description="Dashboard summary and analytics endpoints",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan
)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Analytics Service"}

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)


ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top,https://www.aabhar.top").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], # Best practice: list specific methods if possible
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(analytics_router, prefix="/v1/dashboard", tags=["Dashboard"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.analytics.main:app", host="0.0.0.0", port=8008, reload=True)