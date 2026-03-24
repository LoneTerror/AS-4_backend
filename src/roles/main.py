import uvicorn
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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

from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import db
from src.roles.router import router
from src.common.route_registry import register_app_routes

# ── Route configuration ───────────────────────────────────────────────────────
#
# Route keys MUST match the format built by route_registry._extract_routes:
#
#   f"{METHOD}:{root_path}{route.path}"
#
# This app has root_path="/v1/roles" and the router registers bare paths
# like "/list", "/employees", etc.  So the keys are:
#
#   GET:/v1/roles/list          (not GET:/v1/roles  — that would be the root)
#   POST:/v1/roles/create
#   etc.
#
# TIP: On startup, route_registry logs every route key it finds at DEBUG
# level.  Set LOG_LEVEL=DEBUG once to verify all keys match what you have
# here, then drop back to INFO.
# ─────────────────────────────────────────────────────────────────────────────

ROLE_OVERRIDES: dict[str, list[str]] = {
    # ── Roles ─────────────────────────────────────────────────────────────────
    "GET:/v1/roles/list":                           ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/roles/create":                        ["SUPER_ADMIN"],

    # ── Employee ↔ Role ───────────────────────────────────────────────────────
    "GET:/v1/roles/employees":                      ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/roles/assign":                        ["SUPER_ADMIN"],
    "POST:/v1/roles/revoke":                        ["SUPER_ADMIN"],

    # ── Route permissions ─────────────────────────────────────────────────────
    "GET:/v1/roles/route-permissions":              ["SUPER_ADMIN"],
    "POST:/v1/roles/route-permissions":             ["SUPER_ADMIN"],
    "PATCH:/v1/roles/route-permissions":            ["SUPER_ADMIN"],
    "PATCH:/v1/roles/route-permissions/title":      ["SUPER_ADMIN"],
}

ROUTE_TITLES: dict[str, str] = {
    "GET:/v1/roles/list":                           "List Roles",
    "POST:/v1/roles/create":                        "Create Role",
    "GET:/v1/roles/employees":                      "List Employee Role Assignments",
    "POST:/v1/roles/assign":                        "Assign Role to Employee",
    "POST:/v1/roles/revoke":                        "Revoke Role from Employee",
    "GET:/v1/roles/route-permissions":              "List Route Permissions",
    "POST:/v1/roles/route-permissions":             "Add Route Permission",
    "PATCH:/v1/roles/route-permissions":            "Remove Route Permission",
    "PATCH:/v1/roles/route-permissions/title":      "Update Route Display Title",
    "GET:/v1/roles/my-permissions": "Get My Route Permissions",
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
        always_public_routes={
            "GET:/v1/roles/my-permissions",   # <-- ADD THIS LINE
        },
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
    # root_path is the reverse-proxy strip prefix.
    # route_registry prepends this to every route.path to build the DB key.
    root_path="/v1/roles",
    openapi_url="/openapi.json",
    docs_url="/docs",
)

cors_origins_str      = os.getenv("FRONTEND_CORS_ORIGINS", "")
allowed_origins_list  = [o.strip() for o in cors_origins_str.split(",") if o.strip()]

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