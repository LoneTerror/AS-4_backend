from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from contextlib import asynccontextmanager
from src.prisma.client import db, connect_with_retry
from src.auth.router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Auth Service: 🟢 Database Connected")
    yield
    await db.disconnect()
    print("Auth Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Auth Service",
    version="1.0.0",
    root_path="/auth",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8005", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Auth Service"}

API_PREFIX = "/v1"
app.include_router(auth_router, prefix=API_PREFIX + "/auth", tags=["Auth"])

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
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
    import uvicorn
    uvicorn.run("src.auth.main:app", host="0.0.0.0", port=8001, reload=True)