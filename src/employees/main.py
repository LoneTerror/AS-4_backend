import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.employees.router import router as emp_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Employee Service: Connecting to Database...")
    await db.connect()
    print("Employee Service: 🟢 Database Connected")
    yield
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
    uvicorn.run("src.employees.main:app", host="0.0.0.0", port=8003, reload=True)