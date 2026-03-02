from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.analytics.router import router as analytics_router
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler
)


# Lifespan — connect / disconnect Prisma
@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: D401
    """Async context manager that connects to and disconnects from the database."""
    await db.connect()
    print("Analytics Service: 🟢 Database Connected")
    yield
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

# Register middleware
app.middleware("http")(request_rate_limit_middleware)

# Register exception handlers
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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

# Health check
@app.get("/health", tags=["System"])
async def health_check():
    """Return a simple health check confirming the service is running."""
    return {"status": "healthy", "service": "Analytics Service"}

# Router — mounted at /v1/dashboard
app.include_router(analytics_router, prefix="/v1/dashboard", tags=["Dashboard"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.analytics.main:app", host="0.0.0.0", port=8008, reload=True)
