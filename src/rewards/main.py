from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from .database import connect_db, disconnect_db

from . import router as rewards_router

limiter = Limiter(key_func=get_remote_address)

# 2. Initialize the FastAPI Application
app = FastAPI(
    title="Reward Microservice",
    description="API for managing the reward catalog and point redemptions.",
    version="1.0.0",
    openapi_url="/v1/openapi.json",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 4. Mount the Routers
# This attaches all the endpoints we wrote in router.py to the main app
app.include_router(rewards_router.router)

@app.on_event("startup")
async def startup():
    await connect_db()

@app.on_event("shutdown")
async def shutdown():
    await disconnect_db()

# 5. Health Check Endpoint
# This is used by Kubernetes or Docker to verify the service is running
@app.get("/")
@app.get("/health")
def health_check():
    return {
        "service": "Reward Microservice",
        "status": "System Operational",
        "version": "0.1.0"
    }