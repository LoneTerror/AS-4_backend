"""Recognition service API router"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Path

from src.common.auth import CurrentUser, get_current_user
from src.recognition.schemas import ReviewCreateRequest, ReviewUpdateRequest
from src.recognition.service import RecognitionService

router = APIRouter(prefix="/reviews", tags=["Recognition"])


@router.get("")
async def list_reviews(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    List reviews with pagination.
    
    - HR_ADMIN can see all reviews
    - Other users can only see reviews they created or received
    """
    return await RecognitionService.list_reviews(page, page_size, current_user)


@router.get("/{id}")
async def get_review(
    id: UUID = Path(..., description="Review ID"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get a specific review by ID.
    
    - HR_ADMIN can see any review
    - Other users can only see reviews they created or received
    """
    return await RecognitionService.get_review(str(id), current_user)


@router.post("", status_code=201)
async def create_review(
    payload: ReviewCreateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Create a new review.
    
    - Only EMPLOYEE or MANAGER roles can create reviews
    - Cannot create self-reviews
    - Receiver must be an active employee
    """
    return await RecognitionService.create_review(payload, current_user)


@router.put("/{id}")
async def update_review(
    payload: ReviewUpdateRequest,
    id: UUID = Path(..., description="Review ID"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Update an existing review.
    
    - Only the reviewer or HR_ADMIN can update a review
    """
    return await RecognitionService.update_review(str(id), payload, current_user)