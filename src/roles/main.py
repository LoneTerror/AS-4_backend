import uvicorn
import os
from fastapi import FastAPI, HTTPException
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

from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import db
from src.roles.router import router
from src.common.route_registry import register_app_routes

# ── Route configuration ───────────────────────────────────────────────────────
ROLE_OVERRIDES: dict[str, list[str]] = {
    # ── Roles ─────────────────────────────────────────────────────────────────
    "GET:/aabhar/v1/roles/list":                           ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/aabhar/v1/roles/create":                        ["SUPER_ADMIN"],

    # ── Employee ↔ Role ───────────────────────────────────────────────────────
    "GET:/aabhar/v1/roles/employees":                      ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/aabhar/v1/roles/assign":                        ["SUPER_ADMIN"],
    "POST:/aabhar/v1/roles/revoke":                        ["SUPER_ADMIN"],

    # ── Route permissions ─────────────────────────────────────────────────────
    "GET:/aabhar/v1/roles/route-permissions":              ["SUPER_ADMIN"],
    "POST:/aabhar/v1/roles/route-permissions":             ["SUPER_ADMIN"],
    "PATCH:/aabhar/v1/roles/route-permissions":            ["SUPER_ADMIN"],
    "PATCH:/aabhar/v1/roles/route-permissions/title":      ["SUPER_ADMIN"],
    "GET:/aabhar/v1/roles/my-permissions":                 ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
}

ROUTE_TITLES: dict[str, str] = {
    "GET:/aabhar/v1/roles/list":                           "List Roles",
    "POST:/aabhar/v1/roles/create":                        "Create Role",
    "GET:/aabhar/v1/roles/employees":                      "List Employee Role Assignments",
    "POST:/aabhar/v1/roles/assign":                        "Assign Role to Employee",
    "POST:/aabhar/v1/roles/revoke":                        "Revoke Role from Employee",
    "GET:/aabhar/v1/roles/route-permissions":              "List Route Permissions",
    "POST:/aabhar/v1/roles/route-permissions":             "Add Route Permission",
    "PATCH:/aabhar/v1/roles/route-permissions":            "Remove Route Permission",
    "PATCH:/aabhar/v1/roles/route-permissions/title":      "Update Route Display Title",
}

# ── OpenTelemetry ─────────────────────────────────────────────────────────────
resource       = Resource.create({"service.name": "rnr-roles"})
provider       = TracerProvider(resource=resource)
otlp_exporter  = OTLPSpanExporter()
processor      = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Roles Service: Connecting to Database...")
    await db.connect()

    # Uncomment and Restart the backend if you have changed any routes or need to remove old lingering routes
    # # This deletes any active route that doesn't start with '/aabhar' prefix
    # await db.route_permissions.delete_many(
    #     where={
    #         "route_key": {"not": {"contains": "/aabhar/v1/"}}
    #     }
    # )
    
    print("Roles Service: 🟢 Database Connected")

    print("Roles Service: Connecting to Redis...")
    try:
        await connect_redis()
        print("Roles Service: ☑️ Redis Connected")
    except Exception as e:
        print(f"Roles Service: ⚠️  Redis unavailable ({e})")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
        route_titles=ROUTE_TITLES,
    )

    yield

    print("Roles Service: Disconnecting Redis...")
    await disconnect_redis()
    print("Roles Service: 🔴 Redis Disconnected")

    print("Roles Service: Disconnecting Database...")
    await db.disconnect()
    print("Roles Service: 🔴 Database Disconnected")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Roles & Permissions Service",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/aabhar/v1/roles",
    openapi_url="/openapi.json",
    docs_url="/docs",
)

initialize_cors_and_middleware(app)

app.add_exception_handler(UniqueViolationError, prisma_unique_violation_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}


FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json",
)

if __name__ == "__main__":
    uvicorn.run("src.roles.main:app", host="0.0.0.0", port=8002, reload=True)