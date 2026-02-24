import asyncio
import json
import os
import redis.asyncio as redis

# Using the default local Redis URL
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CHANNEL_NAME = "hdfc_notifications_demo"

# The user ID you seeded earlier
USER_ID = "e240e18c-6f3a-46e2-a872-4ad28201638e" 

async def publish_test_events():
    print(f"[*] Connecting to Redis at {REDIS_URL}...")
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True)
        
        events = [
            {
                "event": "REWARD_POINTS_ADDED",
                "user_id": USER_ID,
                "points": 500,
                "description": "Bonus for Q1 Performance"
            }
        ]

        print(f"[*] Sending event for User {USER_ID}...")
        
        for event in events:
            await r.publish(CHANNEL_NAME, json.dumps(event))
            print(f"[!] Published: {event['event']}")

        print("[*] Done! Check your Notification Service terminal.")

    except Exception as e:
        print(f"[ERROR] Could not connect to Redis: {e}")

if __name__ == "__main__":
    asyncio.run(publish_test_events())