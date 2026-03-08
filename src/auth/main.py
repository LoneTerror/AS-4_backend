import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
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
from src.auth.router import router as auth_router


# ==========================================
# OpenTelemetry Configuration
# ==========================================
# 1. Identify the service in Jaeger
resource = Resource.create({"service.name": "rnr-auth"})
provider = TracerProvider(resource=resource)

# 2. Set up the exporter (Automatically reads OTEL_EXPORTER_OTLP_ENDPOINT)
otlp_exporter = OTLPSpanExporter()

# 3. Process traces in batches in the background
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# 4. Register globally
trace.set_tracer_provider(provider)
# ==========================================

# Grab the env var, default to localhost for local dev fallback
cors_origins_str = os.getenv("FRONTEND_CORS_ORIGINS","http://localhost:8005")
# Split by comma and strip whitespace to create a clean list
allowed_origins_list = [origin.strip() for origin in cors_origins_str.split(",") if origin.strip()]


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
    allow_origins=allowed_origins_list,
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
    import uvicorn
    uvicorn.run("src.auth.main:app", host="0.0.0.0", port=8001, reload=True)