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

router           = APIRouter(prefix="/reviews")
categories_router = APIRouter(prefix="/review-categories")


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW CATEGORIES
# ─────────────────────────────────────────────────────────────────────────────

@categories_router.get(
    "",
    response_model=PaginatedReviewCategoryResponse,
    response_model_exclude_none=True,
    summary="List Review Categories",
    description=(
        "Returns all active review categories with their points multipliers.\n\n"
        "Call this first to get valid `category_ids` UUIDs before creating a review. "
        "You can select **1–5 tags** per review; the points multiplier will be the "
        "**average** of all selected category multipliers."
    ),
)
async def list_review_categories(
    page:        int  = Query(1,    ge=1),
    page_size:   int  = Query(20,   ge=1, le=100),
    active_only: bool = Query(True, description="Return only active categories"),
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    ),
):
    return await RecognitionService.list_review_categories(page, page_size, active_only)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEWS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=PaginatedReviewResponse,
    response_model_exclude_none=True,
    summary="List Reviews",
)
async def list_reviews(
    page:      int = Query(1,  ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    ),
):
    """
    - **EMPLOYEE / MANAGER**: only reviews they gave or received.
    - **HR_ADMIN / SUPER_ADMIN**: all reviews.
    """
    return await RecognitionService.list_reviews(page, page_size, current_user)


@router.get(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Get Review",
)
async def get_review(
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user),
):
    return await RecognitionService.get_review(str(id), current_user)


# ─────────────────────────────────────────────────────────────────────────────
# Inline OpenAPI schemas
# ─────────────────────────────────────────────────────────────────────────────

_CREATE_REQUEST_BODY = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["receiver_id", "rating", "category_ids", "comment"],
                "properties": {
                    "receiver_id": {
                        "type": "string", "format": "uuid",
                        "description": "UUID of the employee receiving the review",
                        "example": "550e8400-e29b-41d4-a716-446655440000",
                    },
                    "rating": {
                        "type": "integer", "minimum": 1, "maximum": 5,
                        "description": "Rating value 1–5",
                        "example": 4,
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "minItems": 1,
                        "maxItems": 5,
                        "uniqueItems": True,
                        "description": (
                            "1–5 category UUIDs from GET /v1/review-categories. "
                            "Points multiplier = average of all selected multipliers."
                        ),
                        "example": [
                            "dd0e8400-e29b-41d4-a716-446655440000",
                            "dd0e8400-e29b-41d4-a716-446655440001",
                        ],
                    },
                    "comment": {
                        "type": "string", "minLength": 10, "maxLength": 2000,
                        "description": "Review comment (10–2000 chars)",
                        "example": "Excellent work on the Q1 project. Great collaboration and technical skills.",
                    },
                    "image_url": {
                        "type": "string", "format": "uri", "maxLength": 500,
                        "example": "https://cdn.company.com/reviews/image123.jpg",
                    },
                    "video_url": {
                        "type": "string", "format": "uri", "maxLength": 500,
                        "example": "https://cdn.company.com/reviews/video123.mp4",
                    },
                },
                "example": {
                    "receiver_id":  "550e8400-e29b-41d4-a716-446655440000",
                    "rating":       4,
                    "category_ids": [
                        "dd0e8400-e29b-41d4-a716-446655440000",
                        "dd0e8400-e29b-41d4-a716-446655440001",
                    ],
                    "comment": "Excellent work on the Q1 project. Great collaboration and technical skills.",
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
                "description": (
                    "At least one field required. "
                    "category_ids replaces all tags and triggers points recalculation."
                ),
                "properties": {
                    "rating": {
                        "type": "integer", "minimum": 1, "maximum": 5,
                        "description": "Updated rating (1–5). Triggers recalculation.",
                        "example": 5,
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "string", "format": "uuid"},
                        "minItems": 1,
                        "maxItems": 5,
                        "uniqueItems": True,
                        "description": "Updated 1–5 tag UUIDs. Replaces existing tags. Triggers recalculation.",
                        "example": [
                            "dd0e8400-e29b-41d4-a716-446655440000",
                            "dd0e8400-e29b-41d4-a716-446655440002",
                        ],
                    },
                    "comment": {
                        "type": "string", "minLength": 10, "maxLength": 2000,
                        "example": "Updated: Outstanding performance throughout the quarter.",
                    },
                    "image_url": {"type": "string", "format": "uri", "maxLength": 500},
                    "video_url": {"type": "string", "format": "uri", "maxLength": 500},
                },
                "example": {
                    "rating":       5,
                    "category_ids": [
                        "dd0e8400-e29b-41d4-a716-446655440000",
                        "dd0e8400-e29b-41d4-a716-446655440002",
                    ],
                    "comment": "Updated: Outstanding performance throughout the quarter.",
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
        "**Required:** `receiver_id`, `rating` (1–5), `category_ids` (1–5 UUIDs), "
        "`comment` (10–2000 chars).\n\n"
        "## Multi-category tagging\n\n"
        "Select 1–5 category tags per review. Points formula:\n\n"
        "`rating × avg(category_multipliers) × reviewer_weight × seasonal_multiplier`\n\n"
        "Using more tags does **not** inflate points — the average keeps it fair.\n\n"
        "## Steps\n"
        "1. Call **`GET /v1/review-categories`** → copy one or more `category_id` UUIDs\n"
        "2. Pass them as the `category_ids` array\n"
        "3. Replace `receiver_id` with a real active employee UUID (not your own)\n\n"
        "All multipliers are frozen as snapshots at write time."
    ),
    openapi_extra={"requestBody": _CREATE_REQUEST_BODY},
)
async def create_review(
    payload: ReviewCreateRequest,
    current_user: CurrentUser = Depends(require_roles("EMPLOYEE", "MANAGER")),
):
    return await RecognitionService.create_review(payload, current_user)


@router.put(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Update Review",
    description=(
        "Update an existing review. At least one field must be supplied.\n\n"
        "Sending a new `category_ids` array **replaces** all existing tags and "
        "triggers points recalculation. The receiver's wallet is adjusted by the delta.\n\n"
        "> ⚠️ Call `GET /v1/review-categories` first to get valid category UUIDs."
    ),
    openapi_extra={"requestBody": _UPDATE_REQUEST_BODY},
)
async def update_review(
    payload: ReviewUpdateRequest,
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    - **Review creator**: can update their own reviews.
    - **HR_ADMIN / SUPER_ADMIN**: can update any review.
    """
    return await RecognitionService.update_review(str(id), payload, current_user)