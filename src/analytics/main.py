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
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    "GET:/v1/dashboard/leaderboard":             ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/dashboard/recent-reviews":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/dashboard/teams":                   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/dashboard/teams/{department_id}":   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/dashboard/platform-stats":          ["SUPER_ADMIN", "HR_ADMIN"],
}


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.include_router(analytics_router, prefix="/v1/dashboard", tags=["Dashboard"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.analytics.main:app", host="0.0.0.0", port=8008, reload=True)