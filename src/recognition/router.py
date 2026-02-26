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
        "Clients should call this endpoint to build a category picker UI and "
        "obtain the category_id required when creating or updating a review."
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


@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
    response_model_exclude_none=True,
    summary="Create Review",
    description=(
        "Create a new performance review. "
        "Supply a `category_id` from GET /v1/review-categories."
    ),
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
    description="Update an existing review. Points are recalculated if rating or category changes.",
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