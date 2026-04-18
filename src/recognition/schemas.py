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

    - receiver_id  : UUID of the employee being reviewed
    - comment      : 10–2000 characters
    - category_ids : 1–5 unique UUIDs from GET /aabhar/v1/review-categories.
                     Points = sum of all selected multipliers × reviewer weight.
    - image_url    : Optional HTTPS URL (max 500 chars)
    - video_url    : Optional HTTPS URL (max 500 chars)
    """
    receiver_id: UUID = Field(..., description="UUID of the employee receiving the review")
    comment: str = Field(..., min_length=10, max_length=2000, description="Review comment (10–2000 chars)")
    category_ids: List[UUID] = Field(
        ...,
        min_length=1,
        max_length=5,
        description=(
            "1–5 review category UUIDs from GET /aabhar/v1/review-categories. "
            "Points = sum of all selected category multipliers × reviewer weight."
        )
    )
    image_url: Optional[HttpUrl] = Field(None, description="Optional image URL (max 500 chars)")
    video_url: Optional[HttpUrl] = Field(None, description="Optional video URL (max 500 chars)")

    model_config = {"extra": "forbid"}

    @field_validator("category_ids")
    @classmethod
    def validate_unique_categories(cls, v):
        if len(v) != len(set(v)):
            raise ValueError("Duplicate category IDs are not allowed")
        return v

    @field_validator("image_url", "video_url")
    @classmethod
    def validate_url_length(cls, v):
        if v and len(str(v)) > 500:
            raise ValueError("URL must not exceed 500 characters")
        return v


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class ReviewUpdateRequest(BaseModel):
    """
    At least one field must be supplied.
    Providing category_ids replaces ALL existing tags and triggers points recalculation.
    """
    comment: Optional[str] = Field(None, min_length=10, max_length=2000, description="Updated comment")
    category_ids: Optional[List[UUID]] = Field(
        None,
        min_length=1,
        max_length=5,
        description="Updated tag list (1–5 UUIDs). Replaces existing tags. Triggers recalculation."
    )
    image_url: Optional[HttpUrl] = Field(None, description="Updated image URL")
    video_url: Optional[HttpUrl] = Field(None, description="Updated video URL")

    model_config = {"extra": "forbid"}

    @field_validator("category_ids")
    @classmethod
    def validate_unique_categories(cls, v):
        if v is not None and len(v) != len(set(v)):
            raise ValueError("Duplicate category IDs are not allowed")
        return v

    @field_validator("image_url", "video_url")
    @classmethod
    def validate_url_length(cls, v):
        if v and len(str(v)) > 500:
            raise ValueError("URL must not exceed 500 characters")
        return v

    @model_validator(mode="after")
    def validate_not_empty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one field must be provided for update")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORY CREATE / UPDATE REQUESTS
# ─────────────────────────────────────────────────────────────────────────────

class ReviewCategoryCreateRequest(BaseModel):
    """
    Request schema for creating a new review category.

    - category_code : Unique short code, e.g. INNOVATION (auto-uppercased)
    - category_name : Unique human-readable label
    - multiplier    : Points multiplier (must be > 0)
    - description   : Optional description
    - is_active     : Defaults to True
    """
    category_code: str   = Field(..., min_length=1, max_length=50,  description="Unique short code, e.g. INNOVATION")
    category_name: str   = Field(..., min_length=1, max_length=100, description="Unique human-readable name")
    multiplier:    float = Field(..., gt=0,                          description="Points multiplier (must be > 0)")
    description:   Optional[str] = Field(None, max_length=500,      description="Optional description")

    model_config = {"extra": "forbid"}

    @field_validator("category_code")
    @classmethod
    def uppercase_code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("category_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class ReviewCategoryUpdateRequest(BaseModel):
    """
    At least one field must be supplied.
    category_code and category_name must remain unique across all categories.
    """
    category_code: Optional[str]   = Field(None, min_length=1, max_length=50,  description="Updated short code (auto-uppercased)")
    category_name: Optional[str]   = Field(None, min_length=1, max_length=100, description="Updated human-readable name")
    multiplier:    Optional[float] = Field(None, gt=0,                          description="Updated points multiplier (must be > 0)")
    description:   Optional[str]   = Field(None, max_length=500,                description="Updated description")
    is_active:     Optional[bool]  = Field(None,                                description="Activate or deactivate the category")

    model_config = {"extra": "forbid"}

    @field_validator("category_code")
    @classmethod
    def uppercase_code(cls, v: Optional[str]) -> Optional[str]:
        return v.strip().upper() if v else v

    @field_validator("category_name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v

    @model_validator(mode="after")
    def validate_not_empty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("At least one field must be provided for update")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORY RESPONSE  (for GET /aabhar/v1/review-categories)
# ─────────────────────────────────────────────────────────────────────────────

class ReviewCategoryResponse(BaseModel):
    category_id:   UUID          = Field(..., description="Unique category identifier")
    category_code: str           = Field(..., description="Short code e.g. INNOVATION")
    category_name: str           = Field(..., description="Human-readable name")
    multiplier:    float         = Field(..., description="Points multiplier for this category")
    description:   Optional[str] = Field(None)
    is_active:     bool          = Field(...)

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
# CATEGORY TAG SNAPSHOT  (nested inside ReviewResponse)
# ─────────────────────────────────────────────────────────────────────────────

class ReviewCategoryTagResponse(BaseModel):
    """
    One row from review_category_tags — the frozen multiplier snapshot
    ensures historical point calculations stay reproducible even if an
    admin later edits a category's multiplier.
    """
    category_id:         UUID  = Field(..., description="Category UUID")
    category_code:       str   = Field(..., description="Category code at write time")
    multiplier_snapshot: float = Field(..., description="Multiplier frozen at write time")

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW RESPONSE
# ─────────────────────────────────────────────────────────────────────────────

class ReviewResponse(BaseModel):
    """
    Full review response.

    category_tags is the authoritative source for which tags were applied and
    what multiplier each carried at write time.

    category_ids / category_codes are convenience lists derived from category_tags
    by the service layer — no extra DB round-trip required.

    Points fields are Optional so pre-migration rows without points data still
    serialise without errors.
    """
    # ── Core ─────────────────────────────────────────────────────────────────
    review_id:   UUID          = Field(...)
    reviewer_id: UUID          = Field(...)
    receiver_id: UUID          = Field(...)
    comment:     str           = Field(...)
    image_url:   Optional[str] = Field(None)
    video_url:   Optional[str] = Field(None)
    status_id:   UUID          = Field(...)
    review_at:   datetime      = Field(...)
    created_at:  datetime      = Field(...)
    created_by:  UUID          = Field(...)
    updated_at:  datetime      = Field(...)
    updated_by:  UUID          = Field(...)

    # ── Multi-category (authoritative) ───────────────────────────────────────
    category_tags:  Optional[List[ReviewCategoryTagResponse]] = Field(
        None,
        description="Tags with per-tag multiplier snapshots from review_category_tags"
    )
    # Derived convenience fields (populated by service, no extra query)
    category_ids:   Optional[List[UUID]] = Field(None, description="Selected category UUIDs")
    category_codes: Optional[List[str]]  = Field(None, description="Selected category codes")

    # ── Points ────────────────────────────────────────────────────────────────
    raw_points: Optional[float] = Field(
        None,
        description="sum(category_multipliers) × reviewer_weight"
    )

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "review_id":    "990e8400-e29b-41d4-a716-446655440004",
                "reviewer_id":  "880e8400-e29b-41d4-a716-446655440000",
                "receiver_id":  "550e8400-e29b-41d4-a716-446655440000",
                "comment":      "Excellent work on the Q1 project.",
                "category_tags": [
                    {"category_id": "770e8400-e29b-41d4-a716-446655440001",
                     "category_code": "INNOVATION", "multiplier_snapshot": 1.4},
                    {"category_id": "770e8400-e29b-41d4-a716-446655440002",
                     "category_code": "TEAMWORK", "multiplier_snapshot": 1.2},
                ],
                "category_ids":        ["770e8400-e29b-41d4-a716-446655440001",
                                        "770e8400-e29b-41d4-a716-446655440002"],
                "category_codes":      ["INNOVATION", "TEAMWORK"],
                "image_url":           None,
                "video_url":           None,
                "status_id":           "aa0e8400-e29b-41d4-a716-446655440005",
                "review_at":           "2026-02-06T10:30:00.000Z",
                "created_at":          "2026-02-06T10:30:00.000Z",
                "created_by":          "880e8400-e29b-41d4-a716-446655440000",
                "updated_at":          "2026-02-06T10:30:00.000Z",
                "updated_by":          "880e8400-e29b-41d4-a716-446655440000",
                # raw_points = (OWNERSHIP 1.2 + INNOVATION 1.3) × reviewer_weight(1.0) = 2.5
                "raw_points":          2.5,
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────────────

class PaginationMeta(BaseModel):
    current_page: int
    per_page:     int
    total:        int
    total_pages:  int
    has_next:     bool
    has_previous: bool


class PaginatedReviewResponse(BaseModel):
    data:       List[ReviewResponse]
    pagination: PaginationMeta


class PaginatedReviewCategoryResponse(BaseModel):
    data:       List[ReviewCategoryResponse]
    pagination: PaginationMeta