import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager

from src.prisma.client import db, connect_with_retry
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.common.dependencies import close_auth_client
from src.organization.router import departments_router, designations_router, department_types_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Organization Service: Connecting to Database...")
    await connect_with_retry()
    print("Organization Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Organization Service: 💚 Redis Connected")
    except Exception as e:
        print(f"Organization Service: 💔 Redis Disconnected ({e}) — caching disabled")

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
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    lifespan=lifespan
)

origins = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top").split(",")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Organization Service"}

API_PREFIX = "/v1"
app.include_router(departments_router,    prefix=API_PREFIX + "/org/departments",     tags=["Departments"])
app.include_router(designations_router,   prefix=API_PREFIX + "/org/designations",    tags=["Designations"])
app.include_router(department_types_router, prefix=API_PREFIX + "/org/department-types", tags=["Department Types"])

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

if __name__ == "__main__":
    uvicorn.run("src.organization.main:app", host="0.0.0.0", port=8007, reload=True)