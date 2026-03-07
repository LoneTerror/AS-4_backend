"""
src/common/cache.py  (UPDATED — aligned with notifications/redis_client.py)
───────────────────
General-purpose Redis cache layer for API response caching.

Usage
-----
from src.common.cache import cache_get, cache_set, cache_delete, invalidate_pattern

# Read-through helper (most common pattern)
async def get_something():
    cached = await cache_get("my:key")
    if cached is not None:
        return cached
    result = await db.something.find_many(...)
    await cache_set("my:key", result, ttl=300)
    return result

# Invalidate one key
await cache_delete("rewards:catalog")

# Invalidate all keys matching a glob pattern
await invalidate_pattern("dashboard:leaderboard:*")
"""

import json
import logging
from typing import Any, Optional

from src.notifications.redis_client import get_redis

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def cache_get(key: str) -> Optional[Any]:
    """
    Return the deserialised cached value for *key*, or ``None`` on miss/error.
    redis_client uses decode_responses=True so .get() already returns str, not bytes.
    """
    try:
        r = get_redis()
        raw = await r.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as exc:
        logger.warning("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int = 60) -> bool:
    """
    Serialise *value* to JSON and store under *key* with expiry *ttl* seconds.
    Returns True on success, False on error.
    Uses setex() — consistent with notifications/cache.py style.
    """
    try:
        r = get_redis()
        await r.setex(key, ttl, json.dumps(value, default=str))
        return True
    except Exception as exc:
        logger.warning("cache_set(%s) failed: %s", key, exc)
        return False


async def cache_delete(*keys: str) -> None:
    """Delete one or more exact cache keys. Errors are swallowed."""
    if not keys:
        return
    try:
        r = get_redis()
        await r.delete(*keys)
        logger.debug("cache_delete: removed keys=%s", keys)
    except Exception as exc:
        logger.warning("cache_delete%s failed: %s", keys, exc)


async def invalidate_pattern(pattern: str) -> int:
    """
    Delete all keys matching a glob *pattern*.
    Uses scan_iter() — consistent with notifications/cache.py style,
    safe for production (never blocks with KEYS).
    Returns the number of keys deleted. Errors are swallowed.

    Example patterns:
        "dashboard:team:*"
        "org:departments:*"
        "rewards:history:abc-wallet-id:*"
    """
    deleted = 0
    try:
        r = get_redis()
        keys_to_delete = []
        async for key in r.scan_iter(pattern):
            keys_to_delete.append(key)
        if keys_to_delete:
            await r.delete(*keys_to_delete)
            deleted = len(keys_to_delete)
            logger.debug("invalidate_pattern(%s): removed %d keys", pattern, deleted)
    except Exception as exc:
        logger.warning("invalidate_pattern(%s) failed: %s", pattern, exc)
    return deleted