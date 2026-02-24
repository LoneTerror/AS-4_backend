# Change from: from src.database import prisma
from src.prisma.client import db
from .schemas import NotificationCreate
from uuid import UUID

class NotificationService:
    @staticmethod
    async def get_user_notifications(user_id: str, page: int, limit: int):
        skip = (page - 1) * limit
        
        # Changed 'prisma' to 'db'
        total = await db.notification.count(where={"recipient_id": user_id})
        notifications = await db.notification.find_many(
            where={"recipient_id": user_id},
            take=limit,
            skip=skip,
            order={"created_at": "desc"}
        )
        return notifications, total

    @staticmethod
    async def mark_as_read(notification_id: str, user_id: str):
        # Changed 'prisma' to 'db'
        return await db.notification.update_many(
            where={
                "notification_id": notification_id,
                "recipient_id": user_id
            },
            data={"is_read": True}
        )

    @staticmethod
    async def create_notification(data: NotificationCreate):
        # Changed 'prisma' to 'db'
        return await db.notification.create(
            data={
                "title": data.title,
                "message": data.message,
                "recipient_id": str(data.recipient_id),
                "is_read": False
            }
        )