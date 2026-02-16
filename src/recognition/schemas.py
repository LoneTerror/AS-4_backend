from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# -------------------------
# CREATE REQUEST
# -------------------------
class ReviewCreateRequest(BaseModel):
    """
    Request schema for creating a new review.
    
    Validates:
    - receiver_id: Must be a valid UUID
    - rating: Integer between 1-5
    - comment: String between 10-2000 characters
    - image_url: Optional valid HTTPS URL (max 500 chars)
    - video_url: Optional valid HTTPS URL (max 500 chars)
    
    """
    receiver_id: UUID = Field(
        ...,
        description="UUID of the employee receiving the review"
    )
    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="Rating value between 1 (lowest) and 5 (highest)"
    )
    comment: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Review comment text"
    )
    image_url: Optional[HttpUrl] = Field(
        None,
        description="Optional URL to an image (max 500 characters)"
    )
    video_url: Optional[HttpUrl] = Field(
        None,
        description="Optional URL to a video (max 500 characters)"
    )

    model_config = {
        "extra": "forbid",  
        "json_schema_extra": {
            "example": {
                "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
                "rating": 4,
                "comment": "Excellent work on the Q1 project. Great collaboration and technical skills.",
                "image_url": "https://cdn.company.com/reviews/image123.jpg",
                "video_url": "https://cdn.company.com/reviews/video123.mp4"
            }
        }
    }

    @field_validator('image_url', 'video_url')
    @classmethod
    def validate_url_length(cls, v):
        """Ensure URLs don't exceed 500 characters"""
        if v and len(str(v)) > 500:
            raise ValueError('URL must not exceed 500 characters')
        return v


# -------------------------
# UPDATE REQUEST
# -------------------------
class ReviewUpdateRequest(BaseModel):
    """
    Request schema for updating an existing review.

    """
    rating: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="Updated rating value between 1-5"
    )
    comment: Optional[str] = Field(
        None,
        min_length=10,
        max_length=2000,
        description="Updated comment text"
    )
    image_url: Optional[HttpUrl] = Field(
        None,
        description="Updated image URL"
    )
    video_url: Optional[HttpUrl] = Field(
        None,
        description="Updated video URL"
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "example": {
                "rating": 5,
                "comment": "Updated: Outstanding performance throughout the quarter."
            }
        }
    }

    @field_validator('image_url', 'video_url')
    @classmethod
    def validate_url_length(cls, v):
        """Ensure URLs don't exceed 500 characters"""
        if v and len(str(v)) > 500:
            raise ValueError('URL must not exceed 500 characters')
        return v

    @model_validator(mode="after")
    def validate_not_empty(self):
        """Ensure at least one field is provided for update"""
        if not any(self.model_dump(exclude_none=True).values()):
            raise ValueError("At least one field must be provided for update")
        return self


# -------------------------
# RESPONSE MODELS
# -------------------------
class ReviewResponse(BaseModel):
    """
    Response schema for review data.

    """
    review_id: UUID = Field(..., description="Unique review identifier")
    reviewer_id: UUID = Field(..., description="Employee who gave the review")
    receiver_id: UUID = Field(..., description="Employee who received the review")
    rating: int = Field(..., description="Rating value (1-5)")
    comment: str = Field(..., description="Review comment text")
    image_url: Optional[str] = Field(None, description="Image URL if provided")
    video_url: Optional[str] = Field(None, description="Video URL if provided")
    status_id: UUID = Field(..., description="Current review status")
    review_at: datetime = Field(..., description="When the review was given")
    created_at: datetime = Field(..., description="When the record was created")
    created_by: UUID = Field(..., description="Employee who created the record")
    updated_at: datetime = Field(..., description="When the record was last updated")
    updated_by: UUID = Field(..., description="Employee who last updated the record")

    model_config = {
        "from_attributes": True, 
        "json_schema_extra": {
            "example": {
                "review_id": "990e8400-e29b-41d4-a716-446655440004",
                "reviewer_id": "880e8400-e29b-41d4-a716-446655440000",
                "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
                "rating": 4,
                "comment": "Excellent work on the Q1 project. Great collaboration and technical skills.",
                "image_url": "https://cdn.company.com/reviews/image123.jpg",
                "video_url": "https://cdn.company.com/reviews/video123.mp4",
                "status_id": "aa0e8400-e29b-41d4-a716-446655440005",
                "review_at": "2026-02-06T10:30:00.000Z",
                "created_at": "2026-02-06T10:30:00.000Z",
                "created_by": "880e8400-e29b-41d4-a716-446655440000",
                "updated_at": "2026-02-06T10:30:00.000Z",
                "updated_by": "880e8400-e29b-41d4-a716-446655440000"
            }
        }
    }


class PaginationMeta(BaseModel):
    """
    Pagination metadata .
    
    """
    current_page: int = Field(..., description="Current page number (1-indexed)")
    per_page: int = Field(..., description="Number of items per page")
    total: int = Field(..., description="Total number of items across all pages")
    total_pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_previous: bool = Field(..., description="Whether there is a previous page")

    model_config = {
        "json_schema_extra": {
            "example": {
                "current_page": 1,
                "per_page": 20,
                "total": 150,
                "total_pages": 8,
                "has_next": True,
                "has_previous": False
            }
        }
    }


class PaginatedReviewResponse(BaseModel):
    """
    Paginated response containing list of reviews and pagination metadata.
    
    """
    data: List[ReviewResponse] = Field(..., description="List of reviews")
    pagination: PaginationMeta = Field(..., description="Pagination metadata")

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": [
                    {
                        "review_id": "990e8400-e29b-41d4-a716-446655440004",
                        "reviewer_id": "880e8400-e29b-41d4-a716-446655440000",
                        "receiver_id": "550e8400-e29b-41d4-a716-446655440000",
                        "rating": 4,
                        "comment": "Great work!",
                        "image_url": None,
                        "video_url": None,
                        "status_id": "aa0e8400-e29b-41d4-a716-446655440005",
                        "review_at": "2026-02-06T10:30:00.000Z",
                        "created_at": "2026-02-06T10:30:00.000Z",
                        "created_by": "880e8400-e29b-41d4-a716-446655440000",
                        "updated_at": "2026-02-06T10:30:00.000Z",
                        "updated_by": "880e8400-e29b-41d4-a716-446655440000"
                    }
                ],
                "pagination": {
                    "current_page": 1,
                    "per_page": 20,
                    "total": 150,
                    "total_pages": 8,
                    "has_next": True,
                    "has_previous": False
                }
            }
        }
    }