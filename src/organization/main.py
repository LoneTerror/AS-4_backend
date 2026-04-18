import uvicorn
import os
from fastapi import FastAPI, HTTPException
# CORSMiddleware import removed
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager

from fastapi.exceptions import RequestValidationError
from prisma.errors import UniqueViolationError

from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
    prisma_unique_violation_handler
)
from src.common.cors_setup import initialize_cors_and_middleware

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
from src.common.dependencies import close_auth_client
from src.organization.router import (
    departments_router,
    designations_router,
    department_types_router,
    statuses_router,
    audit_logs_router,
)
from src.common.route_registry import register_app_routes

# ── Role overrides ────────────────────────────────────────────────────────────
ROLE_OVERRIDES: dict[str, list[str]] = {
    # Departments
    "GET:/aabhar/v1/organizations/departments":                            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/aabhar/v1/organizations/departments/{department_id}":            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/organizations/departments":                           ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/aabhar/v1/organizations/departments/{department_id}":            ["SUPER_ADMIN", "HR_ADMIN"],
    # Department Types
    "GET:/aabhar/v1/organizations/department-types":                       ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    # Designations
    "GET:/aabhar/v1/organizations/designations":                           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/aabhar/v1/organizations/designations/{designation_id}":          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/aabhar/v1/organizations/designations":                          ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/aabhar/v1/organizations/designations/{designation_id}":          ["SUPER_ADMIN", "HR_ADMIN"],
    # Statuses
    "GET:/aabhar/v1/organizations/statuses":                               ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/aabhar/v1/organizations/statuses/{status_id}":                   ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/aabhar/v1/organizations/statuses":                              ["SUPER_ADMIN"],
    "PUT:/aabhar/v1/organizations/statuses/{status_id}":                   ["SUPER_ADMIN"],
    # Audit Logs
    "GET:/aabhar/v1/organizations/audit-logs":                             ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/aabhar/v1/organizations/audit-logs/{audit_id}":                  ["SUPER_ADMIN", "HR_ADMIN"],
}

# ── Route titles ──────────────────────────────────────────────────────────────
ROUTE_TITLES: dict[str, str] = {
    # Departments
    "GET:/aabhar/v1/organizations/departments":                            "List Departments",
    "GET:/aabhar/v1/organizations/departments/{department_id}":            "Get Department Details",
    "POST:/aabhar/v1/organizations/departments":                           "Create Department",
    "PUT:/aabhar/v1/organizations/departments/{department_id}":            "Update Department",
    # Department Types
    "GET:/aabhar/v1/organizations/department-types":                       "List Department Types",
    # Designations
    "GET:/aabhar/v1/organizations/designations":                           "List Designations",
    "GET:/aabhar/v1/organizations/designations/{designation_id}":          "Get Designation Details",
    "POST:/aabhar/v1/organizations/designations":                          "Create Designation",
    "PUT:/aabhar/v1/organizations/designations/{designation_id}":          "Update Designation",
    # Statuses
    "GET:/aabhar/v1/organizations/statuses":                               "List Statuses",
    "GET:/aabhar/v1/organizations/statuses/{status_id}":                   "Get Status Details",
    "POST:/aabhar/v1/organizations/statuses":                              "Create Status",
    "PUT:/aabhar/v1/organizations/statuses/{status_id}":                   "Update Status",
    # Audit Logs
    "GET:/aabhar/v1/organizations/audit-logs":                             "List Audit Logs",
    "GET:/aabhar/v1/organizations/audit-logs/{audit_id}":                  "Get Audit Log Details",
}

_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

# ── OpenTelemetry ─────────────────────────────────────────────────────────────
resource      = Resource.create({"service.name": "rnr-organization"})
provider      = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter()
processor     = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Organization Service: Connecting to Database...")
    await connect_with_retry()
    print("Organization Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Organization Service: ☑️ Redis Connected")
    except Exception as e:
        print(f"Organization Service: ⚠️  Redis unavailable ({e}) — caching disabled")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES,
    )

    yield

    print("Organization Service: Disconnecting...")
    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Organization Service: 🔴 Database Disconnected")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Organization Service",
    description="Microservice for handling company structure: Departments and Designations",
    version="1.0.0",
    root_path="/aabhar/v1/organizations",
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

initialize_cors_and_middleware(app)

app.middleware("http")(request_rate_limit_middleware)

app.add_exception_handler(UniqueViolationError, prisma_unique_violation_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Organization Service"}


app.include_router(departments_router,          prefix="/departments",          tags=["Departments"])
app.include_router(designations_router,         prefix="/designations",         tags=["Designations"])
app.include_router(department_types_router,     prefix="/department-types",     tags=["Department Types"])
app.include_router(statuses_router,             prefix="/statuses",             tags=["Status Master"])
app.include_router(audit_logs_router,           prefix="/audit-logs",           tags=["Audit Logs"])


# ── OpenAPI schema ────────────────────────────────────────────────────────────
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    for path, path_item in schema.get("paths", {}).items():
        if path in _PUBLIC_PATHS:
            continue
        for operation in path_item.values():
            if isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json",
)

if __name__ == "__main__":
    uvicorn.run("src.organization.main:app", host="0.0.0.0", port=8007, reload=True)