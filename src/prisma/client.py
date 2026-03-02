from prisma import Prisma
import asyncio
import logging

logger = logging.getLogger(__name__)

db = Prisma(auto_register=True)

async def connect_with_retry(max_retries: int = 10, delay: int = 15):
    for attempt in range(1, max_retries + 1):
        try:
            await db.connect(timeout=60)
            logger.info("✅ Database connected successfully")
            return
        except Exception as e:
            logger.warning(f"⚠️ DB connect attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
            else:
                raise