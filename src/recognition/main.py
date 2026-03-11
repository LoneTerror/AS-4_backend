import asyncio
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

# --- OpenTelemetry Imports ---
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# -----------------------------

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
from src.common.route_registry import register_app_routes

ROLE_OVERRIDES = {
    "GET:/v1/recognitions/reviews":                        ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/recognitions/reviews/{id}":                   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/recognitions/reviews":                       ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "PUT:/v1/recognitions/reviews/{id}":                   ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "GET:/v1/recognitions/review-categories":              ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/recognitions/review-categories":             ["SUPER_ADMIN", "HR_ADMIN"],
    "PUT:/v1/recognitions/review-categories/{id}":         ["SUPER_ADMIN", "HR_ADMIN"],
    "GET:/v1/recognitions/digest":                         ["SUPER_ADMIN", "HR_ADMIN", "MANAGER", "EMPLOYEE"],
    "POST:/v1/recognitions/digest/send":                   ["SUPER_ADMIN", "HR_ADMIN"],
}


# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-recognition"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_with_retry()
    print("Recognition Service: 🟢 Database Connected")

    try:
        await connect_redis()
        print("Recognition Service: ☑️ Redis Connected")
    except Exception as e:
        print(f"Recognition Service: ⚠️  Redis unavailable ({e}) — caching disabled")

    sender = EmailSender(SMTPConfig.from_env())
    digest_task = asyncio.create_task(digest_worker_loop(db, sender))

    await register_app_routes(
        app,
        default_roles=["SUPER_ADMIN", "HR_ADMIN"],
        role_overrides=ROLE_OVERRIDES,
    )

    yield

    digest_task.cancel()
    try:
        await digest_task
    except asyncio.CancelledError:
        pass

    await close_auth_client()
    await disconnect_redis()
    await db.disconnect()
    print("Recognition Service: 🔴 Database Disconnected")


app = FastAPI(
    title="Recognition Service",
    version="1.0.0",
    openapi_url="/openapi.json",
    root_path="/v1/recognitions",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "service": "Recognition Service"}


app.middleware("http")(request_rate_limit_middleware)
app.add_exception_handler(Exception, generic_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "X-Correlation-ID"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

app.include_router(recognition_router,       tags=["Reviews"])
app.include_router(review_categories_router, tags=["Review Categories"])
app.include_router(digest_router)


# ==========================================
# Instrument FastAPI
# ==========================================
# Automatically trace HTTP requests, but ignore noisy health and docs endpoints
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,docs,openapi.json,redoc"
)
# ==========================================


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.recognition.main:app", host="0.0.0.0", port=8005, reload=True)