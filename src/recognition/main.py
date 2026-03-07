import os
import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from src.prisma.client import db, connect_with_retry
from src.recognition.router import router as recognition_router
from src.recognition.router import categories_router as review_categories_router
from src.digest.router import router as digest_router
from src.notifications.email_sender import EmailSender, SMTPConfig
from src.notifications.redis_client import connect_redis, disconnect_redis
from src.digest.worker import digest_worker_loop
from src.common.dependencies import close_auth_client
from src.common.middleware import (
    request_rate_limit_middleware,
    http_exception_handler,
    validation_exception_handler,
    generic_exception_handler,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Recognition Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Recognition Service: 💚 Redis Connected")
    except Exception as e:
        print(f"Recognition Service: 💔 Redis Disconnected ({e}) — caching disabled")

    sender = EmailSender(SMTPConfig.from_env())
    digest_task = asyncio.create_task(digest_worker_loop(db, sender))

    yield

    digest_task.cancel()
    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Recognition Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Recognition Service",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    lifespan=lifespan,
)

@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Recognition Service"}

app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://aabhar.top,https://www.aabhar.top").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"], # Best practice: list specific methods if possible
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(recognition_router, prefix="/v1", tags=["Reviews"])
app.include_router(review_categories_router, prefix="/v1", tags=["Review Categories"])
app.include_router(digest_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.recognition.main:app", host="0.0.0.0", port=8005, reload=True)