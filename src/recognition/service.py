"""Recognition service business logic"""
from uuid import UUID
from datetime import datetime
from fastapi import HTTPException

from src.prisma.client import db
from src.common.auth import CurrentUser
from src.recognition.schemas import ReviewCreateRequest, ReviewUpdateRequest


class RecognitionService:
    """Service for handling recognition/review operations"""

    @staticmethod
    async def list_reviews(
        page: int,
        page_size: int,
        current_user: CurrentUser
    ):
        """List reviews with pagination and access control"""
        skip = (page - 1) * page_size
        where = {}

        # Non-HR users see only related reviews
        if "HR_ADMIN" not in current_user.roles:
            where["OR"] = [
                {"reviewerId": current_user.id},
                {"receiverId": current_user.id}
            ]

        total = await db.review.count(where=where)

        data = await db.review.find_many(
            where=where,
            skip=skip,
            take=page_size,
            order={"reviewAt": "desc"}
        )

        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "data": data
        }

    @staticmethod
    async def get_review(review_id: str, current_user: CurrentUser):
        """Get a single review by ID with access control"""
        review = await db.review.find_unique(
            where={"id": review_id}
        )

        if not review:
            raise HTTPException(status_code=404, detail="Review not found")

        # Access control
        if "HR_ADMIN" not in current_user.roles:
            if review.reviewerId != current_user.id and review.receiverId != current_user.id:
                raise HTTPException(status_code=403, detail="Access denied")

        return review

    @staticmethod
    async def create_review(
        payload: ReviewCreateRequest,
        current_user: CurrentUser
    ):
        """Create a new review"""
        # Check if user has permission
        if not any(r in current_user.roles for r in ["EMPLOYEE", "MANAGER"]):
            raise HTTPException(status_code=403, detail="Not allowed")

        # Prevent self-review
        if str(payload.receiver_id) == current_user.id:
            raise HTTPException(status_code=400, detail="Self review not allowed")

        # Validate receiver exists and is active
        receiver = await db.employee.find_unique(
            where={"id": str(payload.receiver_id)},
            include={"status": True}
        )

        if not receiver:
            raise HTTPException(status_code=404, detail="Receiver not found")

        if receiver.status.statusCode != "ACTIVE":
            raise HTTPException(status_code=400, detail="Receiver is not active")

        # Get active review status
        status = await db.statusmaster.find_first(
            where={"entityType": "REVIEW", "statusCode": "ACTIVE"}
        )

        if not status:
            raise HTTPException(status_code=500, detail="Review status missing")

        # Create review
        review = await db.review.create(
            data={
                "reviewerId": current_user.id,
                "receiverId": str(payload.receiver_id),
                "rating": payload.rating,
                "comment": payload.comment,
                "imageUrl": str(payload.image_url) if payload.image_url else None,
                "videoUrl": str(payload.video_url) if payload.video_url else None,
                "statusId": status.id,
                "reviewAt": datetime.utcnow(),
                "createdBy": current_user.id,
                "updatedBy": current_user.id
            }
        )

        return review

    @staticmethod
    async def update_review(
        review_id: str,
        payload: ReviewUpdateRequest,
        current_user: CurrentUser
    ):
        """Update an existing review"""
        review = await db.review.find_unique(
            where={"id": review_id}
        )

        if not review:
            raise HTTPException(status_code=404, detail="Review not found")

        # Only reviewer or HR can edit
        if "HR_ADMIN" not in current_user.roles and review.reviewerId != current_user.id:
            raise HTTPException(status_code=403, detail="Not allowed")

        updated = await db.review.update(
            where={"id": review_id},
            data={
                **payload.dict(exclude_unset=True),
                "updatedBy": current_user.id
            }
        )

        return updated