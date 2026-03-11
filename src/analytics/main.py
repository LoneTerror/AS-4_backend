import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

# ── OpenTelemetry ─────────────────────────────────────────────────────────────
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# ─────────────────────────────────────────────────────────────────────────────

from src.prisma.client import db, connect_with_retry
from src.employees.router import router as emp_router
from src.notifications.router import router as notifications_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.slack_sender import SlackSender, SlackConfig
from src.notifications.worker import email_worker_loop, celebration_worker_loop
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.webhooks.router import router as webhooks_router
from src.common.route_registry import register_app_routes

logger = logging.getLogger(__name__)


# ── OpenTelemetry setup ───────────────────────────────────────────────────────
# Mirrors analytics/main.py exactly:
#   - Always create provider + resource
#   - Only attach OTLP exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set
#   - Never crashes locally when Jaeger is not running
resource = Resource.create({"service.name": "rnr-employees"})
provider = TracerProvider(resource=resource)

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
if otlp_endpoint:
    try:
        otlp_exporter = OTLPSpanExporter()   # reads endpoint from env automatically
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info("OpenTelemetry: OTLP exporter → %s", otlp_endpoint)
    except Exception as exc:
        logger.warning("OpenTelemetry: OTLP init failed (%s) — tracing disabled", exc)
else:
    logger.debug("OpenTelemetry: OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing skipped")

trace.set_tracer_provider(provider)
# ─────────────────────────────────────────────────────────────────────────────


ROLE_OVERRIDES = {
    "GET:/v1/employees/list":                                    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/employees/{employee_id}":                           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/employees/create":                                 ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/v1/employees/{employee_id}":                           ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/employees/{employee_id}":                         ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/employees/notifications":                           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/employees/notifications/unread-count":              ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/employees/notifications/{notification_id}/read":    ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/employees/notifications/read-all":                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/employees/notifications":                          ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/employees/notifications/announcements":            ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/employees/webhooks/hris":                          ["SUPER_ADMIN"],
}

# Paths that must never require a token.
# Used by custom_openapi() to skip BearerAuth injection.
_PUBLIC_PATHS = {"/health"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 1. Database ───────────────────────────────────────────────────────────
    print("Employee Service: Connecting to Database...")
    await connect_with_retry()
    print("Employee Service: 🟢 Database Connected")

    # ── 2. Redis ──────────────────────────────────────────────────────────────
    r = None
    try:
        r = await connect_redis()
        print("Employee Service: 🟢 Redis Connected")
    except Exception as exc:
        logger.warning(
            "Redis unavailable (%s) — workers disabled. "
            "Notifications queue in DB; recovered on next restart.",
            exc,
        )
        print("Employee Service: 🔴 Redis Unavailable — workers disabled")

    # ── 3. Email sender ───────────────────────────────────────────────────────
    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    # ── 4. Slack sender (optional) ────────────────────────────────────────────
    slack_sender: SlackSender | None = None
    try:
        slack_config = SlackConfig.from_env()
        slack_sender = SlackSender(slack_config)
        print("Employee Service: 💬 Slack sender initialised")
    except KeyError as e:
        logger.warning("Slack disabled — missing env var: %s", e)
        print("Employee Service: ⚠️  Slack disabled (missing env var)")

    # Store Redis on app state so routers and the health check can access it
    app.state.redis = r

    # ── 5. Background workers ─────────────────────────────────────────────────
    worker_task = None
    celebration_task = None
    if r is not None:
        worker_task = asyncio.create_task(
            email_worker_loop(db, email_sender, r, slack_sender),
            name="email_notification_worker",
        )
        celebration_task = asyncio.create_task(
            celebration_worker_loop(db, email_sender, r, slack_sender),
            name="celebration_notification_worker",
        )
        print("Employee Service: 📧 Email worker started (Redis queue mode)")
        print("Employee Service: 🎉 Celebration worker started")
    else:
        print("Employee Service: ⚠️  Workers not started — Redis unavailable")

    # ── 6. Yield — app is live, /health is reachable ──────────────────────────
    #
    # register_app_routes runs AFTER yield in a background task so it never
    # blocks startup. Until it completes, check_route_permission falls back
    # to default_roles — the same safe default it has always used.
    print("Employee Service: 🟢 Service is live")

    route_registry_task = asyncio.create_task(
        _load_route_registry(app),
        name="route_registry_loader",
    )

    yield  # ← /health returns 200 from this point on

    # ── Shutdown ──────────────────────────────────────────────────────────────
    route_registry_task.cancel()

    for task in (worker_task, celebration_task):
        if task is None:
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    print("Employee Service: 📧 Workers stopped")

    await disconnect_redis()
    print("Employee Service: 🔴 Redis Disconnected")

    await db.disconnect()
    print("Employee Service: 🔴 Database Disconnected")


async def _load_route_registry(app: FastAPI) -> None:
    """
    Loads route permissions from DB in the background after the app is live.
    Retries once on failure. Falls back to default_roles if both fail.
    """
    for attempt in (1, 2):
        try:
            await asyncio.wait_for(
                register_app_routes(
                    app,
                    default_roles=["SUPER_ADMIN", "HR_ADMIN"],
                    role_overrides=ROLE_OVERRIDES,
                ),
                timeout=30.0,
            )
            print("Employee Service: 🟢 Route permissions loaded")
            return
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            logger.error(
                "register_app_routes timed out (attempt %d/2) — %s",
                attempt,
                "retrying in 5s" if attempt == 1 else "falling back to default role enforcement",
            )
        except Exception as exc:
            logger.error(
                "register_app_routes failed (attempt %d/2): %s — %s",
                attempt,
                exc,
                "retrying in 5s" if attempt == 1 else "falling back to default role enforcement",
            )
        if attempt == 1:
            await asyncio.sleep(5)

    print("Employee Service: ⚠️  Route registry failed — using default roles")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Employee Service",
    description="Microservice for handling employee profiles, hierarchy, and search",
    version="1.0.0",
    root_path="/v1/employees",
    openapi_url="/openapi.json",
    docs_url="/docs",
    lifespan=lifespan,
)

cors_origins_str = os.getenv(
    "FRONTEND_CORS_ORIGINS",
    "http://localhost:8005,http://localhost:8001",
)
allowed_origins_list = [o.strip() for o in cors_origins_str.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["System"])
async def health_check():
    r = getattr(app.state, "redis", None)
    redis_status = "not_configured"

    if r is not None:
        try:
            await asyncio.wait_for(r.ping(), timeout=2.0)
            redis_status = "connected"
        except asyncio.TimeoutError:
            redis_status = "timeout"
        except Exception:
            redis_status = "unavailable"

    return {
        "status": "healthy",
        "service": "Employee Service",
        "redis": redis_status,
    }


# ── Routers — always after /health ───────────────────────────────────────────
app.include_router(notifications_router, tags=["Notifications"])
app.include_router(webhooks_router,      tags=["Webhooks"])
app.include_router(emp_router,           tags=["Employees"])


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

# ── OpenTelemetry FastAPI instrumentation ─────────────────────────────────────
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,/docs,/openapi.json",
)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8003, reload=True)