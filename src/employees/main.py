"""
src/employees/main.py  — Employee Service entry point.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
# CORSMiddleware import removed
from fastapi.openapi.utils import get_openapi
from prisma.errors import UniqueViolationError

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.common.middleware import (
    generic_exception_handler, http_exception_handler,
    prisma_unique_violation_handler, request_rate_limit_middleware,
    validation_exception_handler,
)
from src.common.cors_setup import initialize_cors_and_middleware
from src.common.route_registry import register_app_routes
from src.employees.internal_router import router as internal_router
from src.employees.router import router as emp_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.notifications.router import router as notifications_router
from src.notifications.slack_sender import SlackConfig, SlackSender
from src.notifications.worker import email_worker_loop, process_celebrations
from src.prisma.client import connect_with_retry, db
from src.webhooks.router import router as webhooks_router

logger = logging.getLogger(__name__)

resource = Resource.create({"service.name": "rnr-employees"})
provider = TracerProvider(resource=resource)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
if otlp_endpoint:
    try:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    except Exception as exc:
        logger.warning("OTLP init failed: %s", exc)
trace.set_tracer_provider(provider)

ROLE_OVERRIDES = {
    "GET:/v1/employees/list":                                  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/employees/{employee_id}":                         ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/employees/create":                               ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/v1/employees/{employee_id}":                         ["SUPER_ADMIN", "HR_ADMIN"],
    "PATCH:/v1/employees/{employee_id}":                       ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/employees/notifications":                         ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/employees/notifications/unread-count":            ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/employees/notifications/{notification_id}/read":  ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/employees/notifications/read-all":                ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/employees/notifications":                        ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/employees/notifications/announcements":          ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/employees/webhooks/hris":                        ["SUPER_ADMIN"],
}
ROUTE_TITLES = {
    "GET:/v1/employees/list":                                  "List Employees",
    "GET:/v1/employees/{employee_id}":                         "Get Employee Details",
    "POST:/v1/employees/create":                               "Create Employee",
    "PUT:/v1/employees/{employee_id}":                         "Update Employee",
    "PATCH:/v1/employees/{employee_id}":                       "Partially Update Employee",
    "GET:/v1/employees/notifications":                         "List Notifications",
    "GET:/v1/employees/notifications/unread-count":            "Get Unread Notification Count",
    "PUT:/v1/employees/notifications/{notification_id}/read":  "Mark Notification as Read",
    "PUT:/v1/employees/notifications/read-all":                "Mark All Notifications as Read",
    "POST:/v1/employees/notifications":                        "Send Notification",
    "POST:/v1/employees/notifications/announcements":          "Send Announcement",
    "POST:/v1/employees/webhooks/hris":                        "HRIS Webhook",
}

_PUBLIC_PATHS = {"/health", "/docs", "/redoc", "/openapi.json"}

_CELEB_HOUR   = int(os.getenv("CELEBRATION_CRON_HOUR",  "0"))
_CELEB_MINUTE = int(os.getenv("CELEBRATION_CRON_MINUTE", "5"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Employee Service: 🟢 Database Connected")

    r = None
    try:
        r = await connect_redis()
        print("Employee Service: ☑️  Redis Connected")
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)

    smtp_config  = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    slack_sender: SlackSender | None = None
    try:
        slack_sender = SlackSender(SlackConfig.from_env())
        print("Employee Service: 💬 Slack initialised")
    except KeyError as exc:
        logger.warning("Slack disabled — missing env var: %s", exc)

    app.state.redis = r

    worker_task = None
    if r is not None:
        worker_task = asyncio.create_task(
            email_worker_loop(db, email_sender, r, slack_sender),
            name="email_worker",
        )
        print("Employee Service: 📧 Email worker started")

    scheduler = None
    if r is not None:
        _lock_key = "apscheduler:celebration:lock"
        _lock_ttl = 3600

        async def _run_celebrations() -> None:
            acquired = await r.set(_lock_key, "1", nx=True, ex=_lock_ttl)
            if not acquired:
                logger.info("Celebration job: lock held by another instance — skipping")
                return
            try:
                await process_celebrations(db, email_sender, r, slack_sender)
            finally:
                await r.delete(_lock_key)

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run_celebrations,
            trigger="cron",
            hour=_CELEB_HOUR,
            minute=_CELEB_MINUTE,
            id="daily_celebration_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        print(
            f"Employee Service: 🎂 Celebration scheduler started "
            f"(cron={_CELEB_HOUR:02d}:{_CELEB_MINUTE:02d} daily, Redis lock)"
        )

    registry_task = asyncio.create_task(_load_route_registry(app), name="route_registry")

    yield

    registry_task.cancel()

    if scheduler is not None:
        scheduler.shutdown(wait=False)
        print("Employee Service: 🎂 Celebration scheduler stopped")

    if worker_task is not None:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    await disconnect_redis()
    await db.disconnect()
    print("Employee Service: 🔴 Disconnected")


async def _load_route_registry(app: FastAPI) -> None:
    for attempt in (1, 2):
        try:
            await asyncio.wait_for(
                register_app_routes(
                    app,
                    default_roles=["SUPER_ADMIN", "HR_ADMIN"],
                    role_overrides=ROLE_OVERRIDES,
                    route_titles=ROUTE_TITLES,
                ),
                timeout=30.0,
            )
            print("Employee Service: 🟢 Route permissions loaded")
            return
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return
        except Exception as exc:
            logger.error("register_app_routes failed (attempt %d): %s", attempt, exc)
        if attempt == 1:
            await asyncio.sleep(5)
    print("Employee Service: ⚠️  Route registry failed — using defaults")


app = FastAPI(
    title="Employee Service",
    version="1.0.0",
    root_path="/v1/employees",
    openapi_url="/openapi.json",
    docs_url="/docs",
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
    r = getattr(app.state, "redis", None)
    redis_status = "not_configured"
    if r is not None:
        try:
            await asyncio.wait_for(r.ping(), timeout=2.0)
            redis_status = "connected"
        except Exception:
            redis_status = "unavailable"
    return {"status": "healthy", "service": "Employee Service", "redis": redis_status}


app.include_router(notifications_router, tags=["Notifications"])
app.include_router(webhooks_router,      tags=["Webhooks"])
app.include_router(emp_router,           tags=["Employees"])
app.include_router(internal_router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version,
                        description=app.description, routes=app.routes)
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
FastAPIInstrumentor.instrument_app(app, excluded_urls="health,/docs,/openapi.json,internal")

if __name__ == "__main__":
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8003, reload=True)