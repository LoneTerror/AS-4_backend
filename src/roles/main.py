import uvicorn
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# --- OpenTelemetry Imports ---
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
# -----------------------------

from src.notifications.redis_client import connect_redis, disconnect_redis
from src.prisma.client import db
from src.roles.router import router


# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-roles"})
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
    # -------- STARTUP --------
    print("Roles Service: Connecting to Database...")
    await db.connect()
    print("Roles Service: 🟢 Database Connected")

    print("Roles Service: Connecting to Redis...")
    try:
        await connect_redis()
        print("Roles Service: 🟢 Redis Connected")
    except Exception as e:
        print(f"Roles Service: ⚠️  Redis unavailable ({e})")

    yield

    # -------- SHUTDOWN --------
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
    root_path="/v1/roles", 
    openapi_url="/openapi.json", 
    docs_url="/docs",
)

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ==========================================
# Instrument FastAPI
# ==========================================
# Automatically trace HTTP requests, but ignore noisy health and docs endpoints
FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="health,v1/docs,v1/openapi.json"
)
# ==========================================


if __name__ == "__main__":
    uvicorn.run("src.roles.main:app", host="0.0.0.0", port=8002, reload=True)