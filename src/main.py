"""Main FastAPI application"""
from fastapi import FastAPI
from contextlib import asynccontextmanager

from src.prisma.client import db
from src.recognition.router import router as recognition_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - handles startup and shutdown"""
    # Startup: Connect to database
    await db.connect()
    yield
    # Shutdown: Disconnect from database
    await db.disconnect()


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