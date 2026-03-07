import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import db
from src.roles.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # -------- STARTUP --------
    print("Roles Service: Connecting to Database...")
    await db.connect()
    print("Roles Service: 🟢 Database Connected")

    print("Roles Service: Connecting to Redis...")
    await connect_redis()
    print("Roles Service: 💚 Redis Connected")

    yield

    # -------- SHUTDOWN --------
    print("Roles Service: Disconnecting Redis...")
    await disconnect_redis()
    print("Roles Service: 💔 Redis Disconnected")

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

origins = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top,https://backend.aabhar.top").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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