import math
from datetime import datetime, timezone
from fastapi import HTTPException, status

from src.prisma.client import db
from src.recognition.dependencies import CurrentUser
from src.recognition.schemas import ReviewCreateRequest, ReviewUpdateRequest


class RecognitionService:
    """
    Enterprise-grade service layer for review management.

    Responsibilities:
    - Business rule enforcement
    - RBAC access control
    - Pagination logic
    - Audit field handling
    - Strict contract compliance
    """

    # =========================================================
    # LIST REVIEWS
    # =========================================================
    @staticmethod
    async def list_reviews(
        page: int,
        limit: int,
        current_user: CurrentUser
    ):
        """
        Retrieve paginated reviews with RBAC enforcement.

        Contract:
        - page (1-indexed)
        - limit (max 100)
        - returns { data, pagination }
        """

        skip = (page - 1) * limit
        where = {}

        # Restrict non-admin users to own reviews
        if not any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"]):
            where["OR"] = [
                {"reviewer_id": current_user.id},
                {"receiver_id": current_user.id}
            ]

        # Total count
        total = await db.reviews.count(where=where)

        # Fetch data
        reviews = await db.reviews.find_many(
            where=where,
            skip=skip,
            take=limit,
            order={"review_at": "desc"}
        )

        # Correct zero-result pagination
        total_pages = math.ceil(total / limit) if total > 0 else 0

        return {
            "data": reviews,
            "pagination": {
                "current_page": page,
                "per_page": limit,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_previous": page > 1 and total_pages > 0
            }
        }

    # =========================================================
    # GET REVIEW
    # =========================================================
    @staticmethod
    async def get_review(review_id: str, current_user: CurrentUser):
        """
        Retrieve review by ID with RBAC enforcement.
        """

        review = await db.reviews.find_unique(
            where={"review_id": review_id}
        )

        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found"
            )

        # RBAC
        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = (
            review.reviewer_id == current_user.id or
            review.receiver_id == current_user.id
        )

        if not is_admin and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

        return review

    # =========================================================
    # CREATE REVIEW
    # =========================================================
    @staticmethod
    async def create_review(
        payload: ReviewCreateRequest,
        current_user: CurrentUser
    ):
        """
        Create review with strict contract validation.
        """

        # Self-review protection
        if str(payload.receiver_id) == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Self review not allowed"
            )

        # Validate receiver existence + ACTIVE status
        receiver = await db.employees.find_unique(
            where={"employee_id": str(payload.receiver_id)},
            include={"status_master_employees_status_idTostatus_master": True}
        )

        if not receiver:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Receiver not found"
            )

        if (
            not receiver.status_master_employees_status_idTostatus_master
            or receiver.status_master_employees_status_idTostatus_master.status_code != "ACTIVE"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Receiver is not active"
            )

        # Get REVIEW_ACTIVE status
        review_status = await db.status_master.find_first(
            where={
                "entity_type": "REVIEW",
                "status_code": "REVIEW_ACTIVE"
            }
        )

        if not review_status:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Review status configuration missing"
            )

        now = datetime.now(timezone.utc)

        review = await db.reviews.create(
            data={
                "reviewer_id": current_user.id,
                "receiver_id": str(payload.receiver_id),
                "rating": payload.rating,
                "comment": payload.comment,
                "image_url": str(payload.image_url) if payload.image_url else None,
                "video_url": str(payload.video_url) if payload.video_url else None,
                "status_id": review_status.status_id,
                "review_at": now,
                "created_at": now,
                "created_by": current_user.id,
                "updated_at": now,
                "updated_by": current_user.id
            }
        )

        return review

    # =========================================================
    # UPDATE REVIEW
    # =========================================================
    @staticmethod
    async def update_review(
        review_id: str,
        payload: ReviewUpdateRequest,
        current_user: CurrentUser
    ):
        """
        Update review with RBAC and audit enforcement.
        """

        review = await db.reviews.find_unique(
            where={"review_id": review_id}
        )

        if not review:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Review not found"
            )

        is_admin = any(role in current_user.roles for role in ["HR_ADMIN", "SUPER_ADMIN"])
        is_owner = review.reviewer_id == current_user.id

        if not is_admin and not is_owner:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to update this review"
            )

        update_data = {}

        if payload.rating is not None:
            update_data["rating"] = payload.rating
        if payload.comment is not None:
            update_data["comment"] = payload.comment
        if payload.image_url is not None:
            update_data["image_url"] = str(payload.image_url)
        if payload.video_url is not None:
            update_data["video_url"] = str(payload.video_url)

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided for update"
            )

        update_data["updated_at"] = datetime.now(timezone.utc)
        update_data["updated_by"] = current_user.id

        updated = await db.reviews.update(
            where={"review_id": review_id},
            data=update_data
        )

        return updated
