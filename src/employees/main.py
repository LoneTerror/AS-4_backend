import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
import asyncio

from src.prisma.client import db
from src.employees.router import router as emp_router
from src.notifications.router import router as notifications_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.worker import email_worker_loop

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Employee Service: Connecting to Database...")
    await db.connect()
    print("Employee Service: 🟢 Database Connected")


    smtp_config = SMTPConfig.from_env()
    email_sender = EmailSender(smtp_config)

    worker_task = asyncio.create_task(
        email_worker_loop(db, email_sender),
        name="email_notification_worker",
    )
    print("Employee Service: 📧 Email worker started")


    yield

    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
    print("Employee Service: 📧 Email worker stopped")

    print("Employee Service: Disconnecting Database...")
    await db.disconnect()
    print("Employee Service: 🔴 Database Disconnected")

app = FastAPI(
    title="Employee Service",
    description="Microservice for handling employee profiles, hierarchy, and search",
    version="1.0.0",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan
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

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    schema.setdefault("components", {})
    schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }

    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if isinstance(operation, dict):
                operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

if __name__ == "__main__":
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8002, reload=True)