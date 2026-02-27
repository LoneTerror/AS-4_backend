from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# CREATE REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class ReviewCreateRequest(BaseModel):
    """
    Request schema for creating a new review.

    Validates:
    - receiver_id  : Must be a valid UUID
    - rating       : Integer 1–5
    - comment      : 10–2000 characters
    - category_id  : UUID of an active review_categories row
                     (replaces the old freetext category / ReviewCategory enum
                      now that categories live in the DB)
    - image_url    : Optional valid HTTPS URL (max 500 chars)
    - video_url    : Optional valid HTTPS URL (max 500 chars)
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
        description="Review comment text (10–2000 characters)"
    )
    # ── Category is now a FK to the review_categories table ──────────────────
    # Clients send a category_id (UUID).  The service resolves the multiplier
    # and category_code from the DB.  No more hardcoded enum in the engine.
    category_id: UUID = Field(
        ...,
        description=(
            "UUID of the review category (from GET /v1/review-categories). "
            "Determines the points multiplier applied to this review."
        )
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
    }

    @field_validator("image_url", "video_url")
    @classmethod
    def validate_url_length(cls, v):
        """Ensure URLs don't exceed 500 characters."""
        if v and len(str(v)) > 500:
            raise ValueError("URL must not exceed 500 characters")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class ReviewUpdateRequest(BaseModel):
    """
    Request schema for updating an existing review.
    At least one field must be supplied.

    If category_id or rating changes the service recalculates points.
    """
    rating: Optional[int] = Field(
        None,
        ge=1,
        le=5,
        description="Updated rating value (1–5)"
    )
    comment: Optional[str] = Field(
        None,
        min_length=10,
        max_length=2000,
        description="Updated comment text"
    )
    # FK to review_categories (replaces old category enum)
    category_id: Optional[UUID] = Field(
        None,
        description="Updated review category UUID"
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
    }

    @field_validator("image_url", "video_url")
    @classmethod
    def validate_url_length(cls, v):
        """Ensure URLs don't exceed 500 characters."""
        if v and len(str(v)) > 500:
            raise ValueError("URL must not exceed 500 characters")
        return v

    @model_validator(mode="after")
    def validate_not_empty(self):
        """Ensure at least one field is provided for update."""
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one field must be provided for update")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORY RESPONSE  (new — for GET /v1/review-categories)
# ─────────────────────────────────────────────────────────────────────────────

class ReviewCategoryResponse(BaseModel):
    """
    Public representation of a review_categories row.
    Clients use category_id when creating / updating reviews.
    """
    category_id:   UUID    = Field(..., description="Unique category identifier")
    category_code: str     = Field(..., description="Short code, e.g. INNOVATION")
    category_name: str     = Field(..., description="Human-readable name")
    multiplier:    float   = Field(..., description="Points multiplier for this category")
    description:   Optional[str] = Field(None, description="Optional description")
    is_active:     bool    = Field(..., description="Whether this category is selectable")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "category_id":   "770e8400-e29b-41d4-a716-446655440001",
                "category_code": "INNOVATION",
                "category_name": "Innovation",
                "multiplier":    1.4,
                "description":   "Recognises creative problem-solving and novel ideas",
                "is_active":     True,
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW RESPONSE
# ─────────────────────────────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    """
    Response schema for review data.

    Points-related fields are all Optional so that older DB rows
    (without points data) serialise cleanly.

    category_code is a denormalised snapshot included for convenience —
    clients don't need a separate lookup to display the category label.
    """
    # ── Core contract fields ─────────────────────────────────────────────────
    review_id:   UUID     = Field(..., description="Unique review identifier")
    reviewer_id: UUID     = Field(..., description="Employee who gave the review")
    receiver_id: UUID     = Field(..., description="Employee who received the review")
    rating:      int      = Field(..., description="Rating value (1–5)")
    comment:     str      = Field(..., description="Review comment text")
    image_url:   Optional[str] = Field(None, description="Image URL if provided")
    video_url:   Optional[str] = Field(None, description="Video URL if provided")
    status_id:   UUID     = Field(..., description="Current review status")
    review_at:   datetime = Field(..., description="When the review was given")
    created_at:  datetime = Field(..., description="When the record was created")
    created_by:  UUID     = Field(..., description="Employee who created the record")
    updated_at:  datetime = Field(..., description="When the record was last updated")
    updated_by:  UUID     = Field(..., description="Employee who last updated the record")

    # ── Category reference (DB-driven, replaces old freetext string) ─────────
    category_id:   Optional[UUID] = Field(None, description="FK to review_categories — UUID of the category selected at review time")
    category_code: Optional[str]  = Field(None, description="Denormalised category code snapshot stored at review time (e.g. INNOVATION). Avoids a JOIN on every read.")

    # ── Points enrichment fields (additive — never break existing consumers) ─
    raw_points:           Optional[float] = Field(None, description="Total points awarded at review time (rating × category_multiplier × reviewer_weight × seasonal_multiplier). Frozen snapshot — not affected by later multiplier changes.")
    effective_points:     Optional[float] = Field(None, description="raw_points after quarterly time-decay (decay_rate ^ quarters_since_award). Recalculated on every read.")
    category_multiplier:  Optional[float] = Field(None, description="Snapshot of review_categories.multiplier at the time the review was written.")
    reviewer_weight:      Optional[float] = Field(None, description="Snapshot of roles.reviewer_weight for the reviewer's highest-priority role at review time.")
    seasonal_multiplier:  Optional[float] = Field(None, description="Snapshot of seasonal_multipliers.multiplier for the quarter in which the review was written.")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "review_id":            "990e8400-e29b-41d4-a716-446655440004",
                "reviewer_id":          "880e8400-e29b-41d4-a716-446655440000",
                "receiver_id":          "550e8400-e29b-41d4-a716-446655440000",
                "rating":               4,
                "comment":              "Excellent work on the Q1 project.",
                "category_id":          "770e8400-e29b-41d4-a716-446655440001",
                "category_code":        "INNOVATION",
                "image_url":            "https://cdn.company.com/reviews/image123.jpg",
                "video_url":            "https://cdn.company.com/reviews/video123.mp4",
                "status_id":            "aa0e8400-e29b-41d4-a716-446655440005",
                "review_at":            "2026-02-06T10:30:00.000Z",
                "created_at":           "2026-02-06T10:30:00.000Z",
                "created_by":           "880e8400-e29b-41d4-a716-446655440000",
                "updated_at":           "2026-02-06T10:30:00.000Z",
                "updated_by":           "880e8400-e29b-41d4-a716-446655440000",
                "raw_points":           8.96,
                "effective_points":     8.96,
                "category_multiplier":  1.4,
                "reviewer_weight":      1.6,
                "seasonal_multiplier":  1.0,
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    """Pagination metadata."""
    current_page: int  = Field(..., description="Current page number (1-indexed)")
    per_page:     int  = Field(..., description="Number of items per page")
    total:        int  = Field(..., description="Total number of items across all pages")
    total_pages:  int  = Field(..., description="Total number of pages")
    has_next:     bool = Field(..., description="Whether there is a next page")
    has_previous: bool = Field(..., description="Whether there is a previous page")

    model_config = {
        "json_schema_extra": {
            "example": {
                "current_page": 1,
                "per_page":     20,
                "total":        150,
                "total_pages":  8,
                "has_next":     True,
                "has_previous": False
            }
        }
    }


class PaginatedReviewResponse(BaseModel):
    """Paginated response containing list of reviews and pagination metadata."""
    data:       List[ReviewResponse] = Field(..., description="List of reviews")
    pagination: PaginationMeta       = Field(..., description="Pagination metadata")


class PaginatedReviewCategoryResponse(BaseModel):
    """Paginated response for review categories."""
    data:       List[ReviewCategoryResponse] = Field(..., description="List of review categories")
    pagination: PaginationMeta               = Field(..., description="Pagination metadata")