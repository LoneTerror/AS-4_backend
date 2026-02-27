from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path

from src.recognition.dependencies import CurrentUser, get_current_user, require_roles
from src.recognition.schemas import (
    ReviewCreateRequest,
    ReviewUpdateRequest,
    ReviewResponse,
    PaginatedReviewResponse,
    ReviewCategoryResponse,
    PaginatedReviewCategoryResponse,
)
from src.recognition.service import RecognitionService

router = APIRouter(prefix="/reviews")

# Separate router for the new categories endpoint (no "/reviews" prefix)
categories_router = APIRouter(prefix="/review-categories")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORIES  (new — DB-driven, replaces hardcoded ReviewCategory enum)
# ─────────────────────────────────────────────────────────────────────────────

@categories_router.get(
    "",
    response_model=PaginatedReviewCategoryResponse,
    response_model_exclude_none=True,
    summary="List Review Categories",
    description=(
        "Returns all active review categories with their points multipliers. "
        "Clients **must** call this endpoint first to obtain a valid `category_id` "
        "UUID before creating or updating a review."
    ),
)
async def list_review_categories(
    page:        int  = Query(1,    ge=1,  description="Page number (1-indexed)"),
    page_size:   int  = Query(20,   ge=1, le=100, description="Items per page"),
    active_only: bool = Query(True, description="Return only active categories"),
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    ),
):
    """
    List review categories.

    Access: all authenticated roles.
    """
    return await RecognitionService.list_review_categories(page, page_size, active_only)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=PaginatedReviewResponse,
    response_model_exclude_none=True,
    summary="List Reviews",
    description="Retrieve a paginated list of reviews with optional filtering.",
)
async def list_reviews(
    page:      int = Query(1,  ge=1,       description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    ),
):
    """
    List reviews with pagination.

    - **EMPLOYEE / MANAGER**: only reviews they gave or received.
    - **HR_ADMIN / SUPER_ADMIN**: all reviews.
    """
    return await RecognitionService.list_reviews(page, page_size, current_user)


@router.get(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Get Review",
    description="Retrieve detailed information for a specific review.",
)
async def get_review(
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get a specific review by ID.

    - **EMPLOYEE / MANAGER**: only if they are the reviewer or receiver.
    - **HR_ADMIN / SUPER_ADMIN**: any review.
    """
    return await RecognitionService.get_review(str(id), current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Request body schemas for openapi_extra
#
# WHY inline schemas instead of $ref?
# Using "$ref" + a sibling "example" key is silently ignored by Swagger UI —
# the $ref wins and Swagger regenerates the example alphabetically from the
# Pydantic component schema.  Embedding the full schema here guarantees:
#   1. The "Edit Value" box shows fields in logical order
#   2. The "Schema" tab shows required fields marked as required
#   3. Each field has its description and inline example visible
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["receiver_id", "rating", "category_id", "comment"],
                "properties": {
                    "receiver_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "UUID of the employee receiving the review",
                        "example": "550e8400-e29b-41d4-a716-446655440000",
                    },
                    "rating": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Rating value between 1 (lowest) and 5 (highest)",
                        "example": 4,
                    },
                    "category_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": (
                            "UUID of the review category — fetch valid values from "
                            "GET /v1/review-categories. Determines the points multiplier."
                        ),
                        "example": "dd0e8400-e29b-41d4-a716-446655440000",
                    },
                    "comment": {
                        "type": "string",
                        "minLength": 10,
                        "maxLength": 2000,
                        "description": "Review comment text (10–2000 characters)",
                        "example": "Excellent work on the Q1 project. Great collaboration and technical skills.",
                    },
                    "image_url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 500,
                        "description": "Optional URL to an image (max 500 characters)",
                        "example": "https://cdn.company.com/reviews/image123.jpg",
                    },
                    "video_url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 500,
                        "description": "Optional URL to a video (max 500 characters)",
                        "example": "https://cdn.company.com/reviews/video123.mp4",
                    },
                },
                # Top-level example controls the "Edit Value" box content and order
                "example": {
                    "receiver_id":  "550e8400-e29b-41d4-a716-446655440000",
                    "rating":       4,
                    "category_id":  "dd0e8400-e29b-41d4-a716-446655440000",
                    "comment":      "Excellent work on the Q1 project. Great collaboration and technical skills.",
                    "image_url":    "https://cdn.company.com/reviews/image123.jpg",
                    "video_url":    "https://cdn.company.com/reviews/video123.mp4",
                },
            }
        }
    },
}

_UPDATE_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "description": "At least one field must be provided. Points recalculate if rating or category_id changes.",
                "properties": {
                    "rating": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                        "description": "Updated rating value (1–5). Triggers points recalculation.",
                        "example": 5,
                    },
                    "category_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": (
                            "Updated review category UUID — fetch valid values from "
                            "GET /v1/review-categories. Triggers points recalculation."
                        ),
                        "example": "dd0e8400-e29b-41d4-a716-446655440000",
                    },
                    "comment": {
                        "type": "string",
                        "minLength": 10,
                        "maxLength": 2000,
                        "description": "Updated comment text (10–2000 characters)",
                        "example": "Updated: Outstanding performance throughout the quarter.",
                    },
                    "image_url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 500,
                        "description": "Updated image URL (max 500 characters)",
                        "example": "https://cdn.company.com/reviews/image123.jpg",
                    },
                    "video_url": {
                        "type": "string",
                        "format": "uri",
                        "maxLength": 500,
                        "description": "Updated video URL (max 500 characters)",
                        "example": "https://cdn.company.com/reviews/video123.mp4",
                    },
                },
                "example": {
                    "rating":      5,
                    "category_id": "dd0e8400-e29b-41d4-a716-446655440000",
                    "comment":     "Updated: Outstanding performance throughout the quarter.",
                },
            }
        }
    },
}


@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
    response_model_exclude_none=True,
    summary="Create Review",
    description=(
        "Create a new performance review.\n\n"
        "**Required fields:** `receiver_id`, `rating` (1–5), `category_id`, `comment` (10–2000 chars).\n\n"
        "## Steps to test this endpoint\n\n"
        "1. Call **`GET /v1/review-categories`** (above) → copy a real `category_id` UUID from the response\n"
        "2. Replace the `category_id` value in the request body below with that UUID\n"
        "3. Replace `receiver_id` with a real active employee UUID (must not be your own)\n\n"
        "> ⚠️ **If the Edit Value box shows an old request body**, click **Reset** then re-enter — "
        "Swagger UI caches the last submitted body in the browser.\n\n"
        "Points are calculated automatically: "
        "`rating × category_multiplier × reviewer_weight × seasonal_multiplier` — "
        "all multipliers resolved from DB at write time, stored as immutable snapshots."
    ),
    openapi_extra={"requestBody": _CREATE_REQUEST_BODY},
)
async def create_review(
    payload: ReviewCreateRequest,
    current_user: CurrentUser = Depends(require_roles("EMPLOYEE", "MANAGER")),
):
    """
    Create a new review.

    - Cannot review yourself (422).
    - Receiver must be an active employee (422).
    - Points are calculated automatically from the selected category, reviewer
      role weight, and current seasonal multiplier — all resolved from the DB.
    """
    return await RecognitionService.create_review(payload, current_user)


@router.put(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Update Review",
    description=(
        "Update an existing review. At least one field must be supplied.\n\n"
        "**Points are recalculated** whenever `rating` or `category_id` changes. "
        "The receiver's wallet is adjusted by the delta automatically.\n\n"
        "> ⚠️ **First call `GET /v1/review-categories`** to get a real `category_id` UUID from your database."
    ),
    openapi_extra={"requestBody": _UPDATE_REQUEST_BODY},
)
async def update_review(
    payload: ReviewUpdateRequest,
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Update an existing review.

    - **Review creator**: can update their own reviews.
    - **HR_ADMIN / SUPER_ADMIN**: can update any review.
    """
    return await RecognitionService.update_review(str(id), payload, current_user)