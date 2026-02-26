from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import List, Optional


class ReviewCreditRequest(BaseModel):
    employee_id: UUID
    rating: int
    review_id: UUID
    created_by: UUID

class ReviewCreditResponse(BaseModel):
    transaction_id: UUID
    wallet_id: UUID
    credited_points: int
    message: str


class WalletResponse(BaseModel):
    wallet_id: UUID
    employee_id: UUID
    available_points: int
    redeemed_points: int 
    total_earned_points: int


class WalletBalanceResponse(BaseModel):
    wallet_id: UUID
    available_points: int

class CreditFromReviewRequest(BaseModel):
    review_id: str