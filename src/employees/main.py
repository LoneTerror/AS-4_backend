import uvicorn
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
import asyncio
import logging

from src.prisma.client import db, connect_with_retry
from src.employees.router import router as emp_router
from src.notifications.router import router as notifications_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.slack_sender import SlackSender, SlackConfig
from src.notifications.worker import email_worker_loop, celebration_worker_loop

logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Employee Service: Connecting to Database...")
    await connect_with_retry()
    print("Employee Service: 🟢 Database Connected")

    # ── Email ──────────────────────────────────────────────────────────────
    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    # ── Slack (optional) ───────────────────────────────────────────────────
    slack_sender: SlackSender | None = None
    try:
        slack_config = SlackConfig.from_env()
        slack_sender = SlackSender(slack_config)
        print("Employee Service: 💬 Slack sender initialised")
    except KeyError as e:
        logger.warning("Slack disabled — missing env var: %s. Continuing without Slack.", e)

    # ── Workers ────────────────────────────────────────────────────────────
    worker_task = asyncio.create_task(
        email_worker_loop(db, email_sender, slack_sender),
        name="email_notification_worker",
    )
    celebration_task = asyncio.create_task(
        celebration_worker_loop(db, email_sender, slack_sender),
        name="celebration_notification_worker",
    )
    print("Employee Service: 📧 Email worker started")
    print("Employee Service: 🎉 Celebration worker started")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    for task in (worker_task, celebration_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    print("Employee Service: 📧 Workers stopped")
    print("Employee Service: Disconnecting Database...")
    await db.disconnect()
    print("Employee Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Employee Service",
    description="Microservice for handling employee profiles, hierarchy, and search",
    version="1.0.0",
    root_path="/employees",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8001", "http://localhost:8005"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/v1"
app.include_router(emp_router, prefix=API_PREFIX + "/employees", tags=["Employees"])
app.include_router(notifications_router, tags=["Notifications"])


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Employee Service"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
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

if __name__ == "__main__":
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8003, reload=True)