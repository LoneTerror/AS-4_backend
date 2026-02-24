"""Main FastAPI application"""
import asyncio  # <--- ADDED: Required for background tasks
from fastapi import FastAPI
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.recognition.router import router as recognition_router
from .rewards import router as rewards_router

# <--- ADDED: Notification imports
from src.notification.router import router as notification_router
from src.notification.worker import redis_listener 


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown"""
    # Startup: Connect to database
    await db.connect()
    print("Notification Service: 🟢 DB IS CONNECTED")
    
    # <--- ADDED: Start the Redis background worker
    worker_task = asyncio.create_task(redis_listener())
    
    yield
    
    # Shutdown: Cancel worker and disconnect from database
    worker_task.cancel()  # <--- ADDED: Graceful shutdown for the worker
    await db.disconnect()
    print("Notification Service: 🔴 DB IS DISCONNECTED")


app = FastAPI(
    title="Employee Recognition Platform",
    description="API for employee recognition, reviews, and rewards",
    version="1.0.0",
    lifespan=lifespan
)


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Employee Recognition Platform"
    }


# Include service routers
app.include_router(recognition_router)
app.include_router(rewards_router.router)

# <--- ADDED: Mount the Notification endpoints
app.include_router(notification_router, prefix="/v1/notifications", tags=["Notifications"])