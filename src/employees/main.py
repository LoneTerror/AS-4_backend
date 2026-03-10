import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

# --- OpenTelemetry Imports ---
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# -----------------------------

from src.prisma.client import db, connect_with_retry
from src.employees.router import router as emp_router
from src.notifications.router import router as notifications_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.slack_sender import SlackSender, SlackConfig
from src.notifications.worker import email_worker_loop, celebration_worker_loop
from src.notifications.redis_client import connect_redis, disconnect_redis, get_redis
from src.notifications.service import NotificationService
from src.webhooks.router import router as webhooks_router
from src.common.route_registry import register_app_routes

logger = logging.getLogger(__name__)

# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-employees"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================
ROLE_OVERRIDES = {
    "GET:/v1/employees":                            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/employees/{employee_id}":              ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/employees":                           ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/v1/employees/{employee_id}":              ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/employees/{employee_id}":            ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/notifications":                        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/notifications/unread-count":           ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/notifications/{notification_id}/read": ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/notifications/read-all":               ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/notifications":                       ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/notifications/announcements":         ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/webhooks/hris":                       ["SUPER_ADMIN"],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Employee Service: Connecting to Database...")
    await connect_with_retry()
    print("Employee Service: 🟢 Database Connected")

    try:
        r = await connect_redis()
        print("Employee Service: 🔴 Redis Connected")
    except Exception as exc:
        logger.warning(
            "Redis unavailable (%s) — workers will fall back to DB recovery scan on next restart.",
            exc,
        )
        r = None

    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    slack_sender: SlackSender | None = None
    try:
        slack_config = SlackConfig.from_env()
        slack_sender = SlackSender(slack_config)
        print("Employee Service: 💬 Slack sender initialised")
    except KeyError as e:
        logger.warning("Slack disabled — missing env var: %s. Continuing without Slack.", e)

    app.state.redis = r

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
        logger.warning("Workers not started — Redis unavailable. Notifications will queue in DB.")
        worker_task = None
        celebration_task = None

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
    )

    yield

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
    print("Employee Service: Disconnecting Database...")
    await db.disconnect()
    print("Employee Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Employee Service",
    description="Microservice for handling employee profiles, hierarchy, and search",
    version="1.0.0",
    root_path="/v1/employees", 
    openapi_url="/openapi.json", # Moved to root
    docs_url="/docs",
    lifespan=lifespan,
)

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS", "http://localhost:8005,http://localhost:8001")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(emp_router, tags=["Employees"])
app.include_router(notifications_router, tags=["Notifications"])
app.include_router(webhooks_router,      tags=["Webhooks"])

@app.get("/health", tags=["System"])
async def health_check():
    r = app.state.redis
    redis_ok = False
    if r:
        try:
            await r.ping()
            redis_ok = True
        except Exception:
            pass
    return {
        "status": "healthy",
        "service": "Employee Service",
        "redis": "connected" if redis_ok else "unavailable",
    }


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
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8003, reload=True)