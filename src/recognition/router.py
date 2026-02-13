"""Recognition service API router (Contract-Compliant Version)"""

from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path

from src.recognition.dependencies import CurrentUser, get_current_user, require_roles
from src.recognition.schemas import (
    ReviewCreateRequest,
    ReviewUpdateRequest,
    ReviewResponse,
    PaginatedReviewResponse
)
from src.recognition.service import RecognitionService

router = APIRouter(prefix="/reviews")


# -----------------------------------------------------
# LIST REVIEWS
# -----------------------------------------------------
@router.get(
    "",
    response_model=PaginatedReviewResponse,
    response_model_exclude_none=True,
    summary="List Reviews",
    description="Retrieve a paginated list of reviews with optional filtering"
)
async def list_reviews(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: CurrentUser = Depends(
        require_roles("EMPLOYEE", "MANAGER", "HR_ADMIN", "SUPER_ADMIN")
    )
):
    """
    List reviews with pagination.
    
    Access Control:
    - EMPLOYEE: Can see reviews they gave or received
    - MANAGER: Can see reviews they gave or received
    - HR_ADMIN/SUPER_ADMIN: Can see all reviews
    
    Returns:
        PaginatedReviewResponse with list of reviews and pagination metadata
    """
    return await RecognitionService.list_reviews(page, page_size, current_user)


# -----------------------------------------------------
# GET REVIEW
# -----------------------------------------------------
@router.get(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Get Review",
    description="Retrieve detailed information for a specific review"
)
async def get_review(
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get a specific review by ID.
    
    Access Control:
    - EMPLOYEE/MANAGER: Can only see reviews they gave or received
    - HR_ADMIN/SUPER_ADMIN: Can see any review
    
    Returns:
        ReviewResponse with full review details
        
    Raises:
        404: Review not found
        403: Access denied
    """
    return await RecognitionService.get_review(str(id), current_user)


# -----------------------------------------------------
# CREATE REVIEW
# -----------------------------------------------------
@router.post(
    "",
    response_model=ReviewResponse,
    status_code=201,
    response_model_exclude_none=True,
    summary="Create Review",
    description="Create a new performance review"
)
async def create_review(
    payload: ReviewCreateRequest,
    current_user: CurrentUser = Depends(require_roles("EMPLOYEE", "MANAGER"))
):
    """
    Create a new review.
    
    Business Rules:
    - Cannot review yourself
    - Receiver must be an active employee
    - Rating must be between 1-5
    - Comment must be 10-2000 characters
    
    Returns:
        ReviewResponse with the created review (HTTP 201)
        
    Raises:
        404: Receiver not found
        422: Self-review not allowed or receiver not active
        400: Validation errors
    """
    return await RecognitionService.create_review(payload, current_user)


# -----------------------------------------------------
# UPDATE REVIEW
# -----------------------------------------------------
@router.put(
    "/{id}",
    response_model=ReviewResponse,
    response_model_exclude_none=True,
    summary="Update Review",
    description="Update an existing review"
)
async def update_review(
    payload: ReviewUpdateRequest,
    id: UUID = Path(..., description="Unique review identifier"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Update an existing review.
    
    Access Control:
    - Review creator can update their own reviews
    - HR_ADMIN/SUPER_ADMIN can update any review
    
    Returns:
        ReviewResponse with updated review details
        
    Raises:
        404: Review not found
        403: Not allowed to update this review
        400: No fields provided for update
    """
    return await RecognitionService.update_review(str(id), payload, current_user)