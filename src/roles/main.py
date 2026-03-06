# src/roles/main.py

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.roles.router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Roles Service: Connecting to Database...")
    await db.connect()
    print("Roles Service: 🟢 Database Connected")
    yield
    await db.disconnect()


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