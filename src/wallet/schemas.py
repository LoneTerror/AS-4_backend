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

class TransactionCreate(BaseModel):
    wallet_id: UUID
    amount: int
    transaction_type_id: UUID
    description: str | None = None
    reference_number: str


# Nested response models for richer frontend data
class StatusInfo(BaseModel):
    """Status information with code and name"""
    status_id: str
    code: str
    name: str

    @classmethod
    def from_db(cls, status_master):
        """Create from Prisma status_master object"""
        if not status_master:
            return None
        return cls(
            status_id=status_master.status_id,
            code=status_master.status_code,
            name=status_master.status_name
        )

    class Config:
        from_attributes = True


class TransactionTypeInfo(BaseModel):
    """Transaction type information with code, name, and credit flag"""
    type_id: str
    code: str
    name: str
    is_credit: bool

    @classmethod
    def from_db(cls, transaction_types):
        """Create from Prisma transaction_types object"""
        if not transaction_types:
            return None
        return cls(
            type_id=transaction_types.type_id,
            code=transaction_types.type_code,
            name=transaction_types.type_name,
            is_credit=transaction_types.is_credit
        )

    class Config:
        from_attributes = True


class TransactionResponse(BaseModel):
    """Enhanced transaction response with nested status and type details"""
    transaction_id: UUID
    wallet_id: UUID
    amount: int
    status: StatusInfo
    transaction_type: TransactionTypeInfo
    reference_number: str
    description: Optional[str]
    transaction_at: datetime
    created_at: datetime
    updated_at: datetime
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None

    class Config:
        from_attributes = True


class TransactionListResponse(BaseModel):
    page: int
    limit: int
    total: int
    transactions: List[TransactionResponse]


class WalletResponse(BaseModel):
    wallet_id: UUID
    employee_id: UUID
    available_points: int
    redeemed_points: int 
    total_earned_points: int


class WalletBalanceResponse(BaseModel):
    wallet_id: UUID
    available_points: int
