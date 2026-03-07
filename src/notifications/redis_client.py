# src/notifications/redis_client.py
"""
Redis / Valkey client — single shared instance for the whole process.

Compatible with:
  - Redis Cloud free tier (redis://...)          ← recommended, free forever
  - Valkey (drop-in Redis replacement)
  - AWS ElastiCache (rediss://... for TLS)

Set REDIS_URL in your .env:
  redis://localhost:6379/0                        # local dev
  redis://:password@host:6379/0                   # Redis Cloud / Valkey
  rediss://:password@host:6380/0                  # TLS (ElastiCache)
"""

import logging
import os

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Module-level singleton — initialised in lifespan, used everywhere
redis: aioredis.Redis | None = None


async def connect_redis() -> aioredis.Redis:
    """Call once at startup inside lifespan. Returns the connected client."""
    global redis
    redis = aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=30,        # must be > BRPOP timeout (4s) — was 5, caused race
        socket_keepalive=True,    # keeps idle connections alive on Redis Cloud
        socket_keepalive_options={},
        retry_on_timeout=True,
        health_check_interval=15, # ping every 15s to detect stale connections early
    )
    # Ping to validate connection at startup rather than discovering it on first use
    await redis.ping()
    logger.info("Redis connected: %s", REDIS_URL.split("@")[-1])  # hide credentials
    return redis


async def disconnect_redis() -> None:
    global redis
    if redis:
        await redis.aclose()
        redis = None
        logger.info("Redis disconnected.")


def get_redis() -> aioredis.Redis:
    """Dependency / helper — always returns the live client."""
    if redis is None:
        raise RuntimeError("Redis not initialised — call connect_redis() in lifespan first.")
    return redis