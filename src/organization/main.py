import uvicorn
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    seasonal_multipliers_router,
)
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    # ── Departments ───────────────────────────────────────────────────────────
    "GET:/departments":                               ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/departments/{department_id}":               ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/departments":                              ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/departments/{department_id}":               ["SUPER_ADMIN", "HR_ADMIN"],
    
    # ── Department Types ──────────────────────────────────────────────────────
    "GET:/department-types":                          ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    
    # ── Designations ──────────────────────────────────────────────────────────
    "GET:/designations":                              ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/designations/{designation_id}":             ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/designations":                             ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/designations/{designation_id}":             ["SUPER_ADMIN", "HR_ADMIN"],
    
    # ── Statuses ──────────────────────────────────────────────────────────────
    "GET:/statuses":                                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/statuses/{status_id}":                      ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/statuses":                                 ["SUPER_ADMIN"],
    "PUT:/statuses/{status_id}":                      ["SUPER_ADMIN"],
    
    # ── Seasonal Multipliers ──────────────────────────────────────────────────
    "GET:/seasonal-multipliers":                      ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/seasonal-multipliers/active":               ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/seasonal-multipliers":                     ["SUPER_ADMIN"],
    "PUT:/seasonal-multipliers/{mult_id}":            ["SUPER_ADMIN"],
    "DELETE:/seasonal-multipliers/{mult_id}":         ["SUPER_ADMIN"],
    
    # ── Audit Logs ────────────────────────────────────────────────────────────
    "GET:/audit-logs":                                ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/audit-logs/{audit_id}":                     ["SUPER_ADMIN", "HR_ADMIN"],
}
# ── Recognitions Service ──────────────────────────────────────────────────────
ROUTE_TITLES = {
    "GET:/v1/recognitions/reviews":                         "List Reviews",
    "GET:/v1/recognitions/reviews/{id}":                    "Get Review Details",
    "POST:/v1/recognitions/reviews":                        "Submit Review",
    "PUT:/v1/recognitions/reviews/{id}":                    "Update Review",
    "GET:/v1/recognitions/review-categories":               "List Review Categories",
    "POST:/v1/recognitions/review-categories":              "Create Review Category",
    "PUT:/v1/recognitions/review-categories/{id}":          "Update Review Category",
    "GET:/v1/recognitions/digest":                          "View Recognition Digest",
    "POST:/v1/recognitions/digest/send":                    "Send Recognition Digest",
}


# ── Organizations Service ─────────────────────────────────────────────────────
ROUTE_TITLES = {
    # Departments
    "GET:/v1/organizations/departments":                                "List Departments",
    "GET:/v1/organizations/departments/{department_id}":                "Get Department Details",
    "POST:/v1/organizations/departments":                               "Create Department",
    "PUT:/v1/organizations/departments/{department_id}":                "Update Department",
    # Department Types
    "GET:/v1/organizations/department-types":                           "List Department Types",
    # Designations
    "GET:/v1/organizations/designations":                               "List Designations",
    "GET:/v1/organizations/designations/{designation_id}":              "Get Designation Details",
    "POST:/v1/organizations/designations":                              "Create Designation",
    "PUT:/v1/organizations/designations/{designation_id}":              "Update Designation",
    # Statuses
    "GET:/v1/organizations/statuses":                                   "List Statuses",
    "GET:/v1/organizations/statuses/{status_id}":                       "Get Status Details",
    "POST:/v1/organizations/statuses":                                  "Create Status",
    "PUT:/v1/organizations/statuses/{status_id}":                       "Update Status",
    # Seasonal Multipliers
    "GET:/v1/organizations/seasonal-multipliers":                       "List Seasonal Multipliers",
    "GET:/v1/organizations/seasonal-multipliers/active":                "Get Active Seasonal Multiplier",
    "POST:/v1/organizations/seasonal-multipliers":                      "Create Seasonal Multiplier",
    "PUT:/v1/organizations/seasonal-multipliers/{mult_id}":             "Update Seasonal Multiplier",
    "DELETE:/v1/organizations/seasonal-multipliers/{mult_id}":          "Delete Seasonal Multiplier",
    # Audit Logs
    "GET:/v1/organizations/audit-logs":                                 "List Audit Logs",
    "GET:/v1/organizations/audit-logs/{audit_id}":                      "Get Audit Log Details",
}
# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-organization"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================


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


app = FastAPI(
    title="Organization Service",
    description="Microservice for handling company structure: Departments and Designations",
    version="1.0.0",
    root_path="/v1/organizations", 
    openapi_url="/openapi.json", 
    docs_url="/docs",
    lifespan=lifespan
)


# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS","http://localhost:8005,http://localhost:8001,http://localhost:8003")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(UniqueViolationError, prisma_unique_violation_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Organization Service"}


app.include_router(departments_router,      prefix="/departments",          tags=["Departments"])
app.include_router(designations_router,     prefix="/designations",         tags=["Designations"])
app.include_router(department_types_router, prefix="/department-types",     tags=["Department Types"])
app.include_router(statuses_router,         prefix="/statuses",             tags=["Status Master"])
app.include_router(audit_logs_router,       prefix="/audit-logs",           tags=["Audit Logs"])
app.include_router(seasonal_multipliers_router, prefix="/seasonal-multipliers", tags=["Seasonal Multipliers"])


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi

# ==========================================
# Instrument FastAPI
# ==========================================
# Automatically trace HTTP requests, but ignore noisy health and docs endpoints
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json"
)
# ==========================================

if __name__ == "__main__":
    uvicorn.run("src.organization.main:app", host="0.0.0.0", port=8007, reload=True)