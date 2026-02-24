import asyncio
import json
import redis.asyncio as redis
from .service import NotificationService
from .schemas import NotificationCreate

# CONFIGURATION: Marked for change when moving to production
REDIS_URL = "redis://localhost:6379" 
CHANNEL_NAME = "hdfc_notifications_demo"

async def redis_listener():
    """Background task to listen for events from Redis"""
    r = redis.from_url(REDIS_URL, decode_responses=True)
    async with r.pubsub() as pubsub:
        await pubsub.subscribe(CHANNEL_NAME)
        print(f"[*] Notification Worker: Subscribed to {CHANNEL_NAME}. Waiting for events...")
        
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True)
                if message:
                    # DEMO JSON FORMAT: Marked for change based on project lead's final spec
                    data = json.loads(message["data"])
                    event = data.get("event")
                    user_id = data.get("user_id")

                    if event == "REWARD_POINTS_ADDED":
                        title = "Points Received!"
                        body = f"You received {data.get('points')} points in your wallet."
                    elif event == "RECOGNITION_RECEIVED":
                        title = "New Recognition!"
                        body = f"{data.get('from_name')} just recognized you for your work."
                    elif event == "REWARD_REDEEMED":
                        title = "Redemption Successful"
                        body = "You have redeemed a gift coupon successfully."
                    else:
                        continue

                    # Call your existing service to save to Prisma
                    await NotificationService.create_notification(
                        NotificationCreate(recipient_id=user_id, title=title, message=body)
                    )
                await asyncio.sleep(0.01) # Small sleep to prevent CPU spike
            except Exception as e:
                print(f"Worker Error: {e}")
                await asyncio.sleep(5)