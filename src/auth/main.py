"""src/auth/main.py — Auth Service entry point."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from prisma.errors import UniqueViolationError

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.auth.router import router as auth_router
from src.common.middleware import (
    generic_exception_handler, http_exception_handler,
    prisma_unique_violation_handler, request_rate_limit_middleware,
    validation_exception_handler,
)   
from src.common.cors_setup import initialize_cors_and_middleware
from src.common.dependencies import register_public_paths
from src.common.route_registry import register_app_routes
from src.prisma.client import connect_with_retry, db

# --- OpenTelemetry Configuration ---
resource      = Resource.create({"service.name": "rnr-auth"})
provider      = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter()
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

ROLE_OVERRIDES: dict[str, list[str]] = {
    "POST:/aabhar/v1/auth/login":           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/logout":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/refresh":         ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/forgot-password": ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/reset-password":  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/signup":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/validate":        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/auth/bulk-import":     ["SUPER_ADMIN", "HR_ADMIN"],
}
ROUTE_TITLES: dict[str, str] = {
    "POST:/aabhar/v1/auth/login":           "Login",
    "POST:/aabhar/v1/auth/logout":          "Logout",
    "POST:/aabhar/v1/auth/refresh":         "Refresh Access Token",
    "POST:/aabhar/v1/auth/forgot-password": "Request Password Reset",
    "POST:/aabhar/v1/auth/reset-password":  "Reset Password",
    "POST:/aabhar/v1/auth/signup":          "Sign Up",
    "POST:/aabhar/v1/auth/validate":        "Validate Token",
    "POST:/aabhar/v1/auth/bulk-import":     "Bulk Import Employees",
}

ALWAYS_PUBLIC_ROUTES: set[str] = {
    "POST:/aabhar/v1/auth/login",
    "POST:/aabhar/v1/auth/refresh",
    "POST:/aabhar/v1/auth/validate",
    "POST:/aabhar/v1/auth/forgot-password",
    "POST:/aabhar/v1/auth/reset-password",
}

_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json",
                "/login", "/refresh", "/validate", "/forgot-password", "/reset-password"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Auth Service: 🟢 Database Connected")

    register_public_paths(
        "/login",           "/aabhar/v1/auth/login",
        "/refresh",         "/aabhar/v1/auth/refresh",
        "/validate",        "/aabhar/v1/auth/validate",
        "/forgot-password", "/aabhar/v1/auth/forgot-password",
        "/reset-password",  "/aabhar/v1/auth/reset-password",
    )

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES, 
        always_public_routes=ALWAYS_PUBLIC_ROUTES,
    )
    yield
    await db.disconnect()
    print("Auth Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Auth Service", version="1.0.0",
    root_path="/aabhar/v1/auth", openapi_url="/openapi.json", docs_url="/docs",
    lifespan=lifespan,
)

initialize_cors_and_middleware(app)

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(UniqueViolationError,   prisma_unique_violation_handler)
app.add_exception_handler(HTTPException,          http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception,              generic_exception_handler)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Auth Service"}


app.include_router(auth_router, tags=["Auth"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    for path, path_item in schema.get("paths", {}).items():
        if path in _PUBLIC_PATHS:
            continue
        for op in path_item.values():
            if isinstance(op, dict):
                op["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
FastAPIInstrumentor.instrument_app(app, excluded_urls="health,/docs,/openapi.json")

if __name__ == "__main__":
    uvicorn.run(
        "src.auth.main:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )