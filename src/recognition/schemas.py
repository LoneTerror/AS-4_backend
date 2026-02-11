"""Recognition service schemas"""
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl


class ReviewCreateRequest(BaseModel):
    """Schema for creating a new review"""
    receiver_id: UUID
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    comment: str = Field(..., min_length=10, max_length=2000, description="Review comment")
    image_url: Optional[HttpUrl] = None
    video_url: Optional[HttpUrl] = None


class ReviewUpdateRequest(BaseModel):
    """Schema for updating an existing review"""
    rating: Optional[int] = Field(None, ge=1, le=5, description="Rating from 1 to 5")
    comment: Optional[str] = Field(None, min_length=10, max_length=2000, description="Review comment")
    image_url: Optional[HttpUrl] = None
    video_url: Optional[HttpUrl] = None