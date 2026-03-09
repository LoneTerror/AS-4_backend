import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import db
from src.roles.router import router
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    "GET:/v1/roles":                ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/roles/employees":      ["SUPER_ADMIN", "HR_ADMIN"],
    "POST:/v1/roles":               ["SUPER_ADMIN"],
    "POST:/v1/roles/assign":        ["SUPER_ADMIN"],
    "POST:/v1/roles/revoke":        ["SUPER_ADMIN"],
    "GET:/v1/route-permissions":    ["SUPER_ADMIN"],
    "POST:/v1/route-permissions":   ["SUPER_ADMIN"],
    "PATCH:/v1/route-permissions":  ["SUPER_ADMIN"],
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Roles Service: Connecting to Database...")
    await db.connect()
    print("Roles Service: 🟢 Database Connected")

    print("Roles Service: Connecting to Redis...")
    await connect_redis()
    print("Roles Service: 🟢 Redis Connected")

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
    )

    yield

    print("Roles Service: Disconnecting Redis...")
    await disconnect_redis()
    print("Roles Service: 🔴 Redis Disconnected")

    print("Roles Service: Disconnecting Database...")
    await db.disconnect()
    print("Roles Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Roles & Permissions Service",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("src.roles.main:app", host="0.0.0.0", port=8002, reload=True)