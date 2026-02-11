from fastapi import FastAPI, Depends, Query, HTTPException, Path
from contextlib import asynccontextmanager
from uuid import UUID
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

from src.prisma.client import db
from typing import List
from fastapi import HTTPException

class CurrentUser:
    def __init__(self, id: str, roles: List[str]):
        self.id = id
        self.roles = roles


async def get_current_user() -> CurrentUser:
    """
    TEMP HARD-CODED USER
    Remove this when JWT / Gateway auth is added.
    """
    return CurrentUser(
        id="110e8400-e29b-41d4-a716-446655440000",  # existing employee_id
        roles=["SUPER_ADMIN"]  # change to HR_ADMIN / MANAGER when needed
    )



# ---------------------------
# Lifespan (DB)
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(
    title="Recognition Service",
    version="1.0.0",
    lifespan=lifespan
)

# =========================================================
# SCHEMAS
# =========================================================

class ReviewCreateRequest(BaseModel):
    receiver_id: UUID
    rating: int = Field(..., ge=1, le=5)
    comment: str = Field(..., min_length=10, max_length=2000)
    image_url: Optional[HttpUrl] = None
    video_url: Optional[HttpUrl] = None


class ReviewUpdateRequest(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = Field(None, min_length=10, max_length=2000)
    image_url: Optional[HttpUrl] = None
    video_url: Optional[HttpUrl] = None


# =========================================================
# GET /reviews  (List)
# =========================================================
@app.get("/reviews")
async def list_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user)
):
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


# =========================================================
# GET /reviews/{id}
# =========================================================
@app.get("/reviews/{id}")
async def get_review(
    id: UUID = Path(...),
    current_user=Depends(get_current_user)
):
    review = await db.review.find_unique(
        where={"id": str(id)}
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Access control
    if "HR_ADMIN" not in current_user.roles:
        if review.reviewerId != current_user.id and review.receiverId != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")

    return review


# =========================================================
# POST /reviews
# =========================================================
@app.post("/reviews", status_code=201)
async def create_review(
    payload: ReviewCreateRequest,
    current_user=Depends(get_current_user)
):
    if not any(r in current_user.roles for r in ["EMPLOYEE", "MANAGER"]):
        raise HTTPException(status_code=403, detail="Not allowed")

    if str(payload.receiver_id) == current_user.id:
        raise HTTPException(status_code=400, detail="Self review not allowed")

    receiver = await db.employee.find_unique(
        where={"id": str(payload.receiver_id)},
        include={"status": True}
    )

    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    if receiver.status.statusCode != "ACTIVE":
        raise HTTPException(status_code=400, detail="Receiver is not active")

    status = await db.statusmaster.find_first(
        where={"entityType": "REVIEW", "statusCode": "ACTIVE"}
    )

    if not status:
        raise HTTPException(status_code=500, detail="Review status missing")

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


# =========================================================
# PUT /reviews/{id}
# =========================================================
@app.put("/reviews/{id}")
async def update_review(
    id: UUID,
    payload: ReviewUpdateRequest,
    current_user=Depends(get_current_user)
):
    review = await db.review.find_unique(
        where={"id": str(id)}
    )

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    # Only reviewer or HR can edit
    if "HR_ADMIN" not in current_user.roles and review.reviewerId != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed")

    updated = await db.review.update(
        where={"id": str(id)},
        data={
            **payload.dict(exclude_unset=True),
            "updatedBy": current_user.id
        }
    )

    return updated
