import logging
import os
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

redis: aioredis.Redis | None = None


async def connect_redis() -> aioredis.Redis:
    global redis

    redis = aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=30,
        socket_keepalive=True,
        retry_on_timeout=True,
        retry_on_error=[ConnectionError],
        health_check_interval=15,
        max_connections=20
    )

    await redis.ping()

    host = REDIS_URL.split("@")[-1]
    logger.info("Redis connected → %s", host)

    return redis


async def disconnect_redis():
    global redis
    if redis:
        await redis.aclose()
        redis = None
        logger.info("Redis disconnected")


def get_redis() -> aioredis.Redis:
    if redis is None:
        raise RuntimeError("Redis not initialised — call connect_redis() in lifespan first.")
    return redis