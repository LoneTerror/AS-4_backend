"""
src/common/cache.py
────────────────────
Two-layer cache:
  L1 — in-process Python dict  (0ms, process-local)
  L2 — Redis                   (~1ms local / ~55ms remote)

Read path:
  1. Check L1 → return immediately on hit (zero Redis round-trip)
  2. Check Redis → back-fill L1 → return on hit
  3. Return None on full miss (caller queries DB)

Write path:
  1. Write Redis (setex) with the chosen TTL tier
  2. Populate L1 with the matching L1 tier TTL

TTL TIERS — use these constants everywhere, in both cache files:
  ┌───────────┬────────────┬───────────┬──────────────────────────────────────┐
  │ Tier      │ L2 (Redis) │ L1 (mem)  │ Use for                              │
  ├───────────┼────────────┼───────────┼──────────────────────────────────────┤
  │ VOLATILE  │    60 s    │   30 s    │ wallet balance, unread counts        │
  │ SHORT     │   300 s    │   60 s    │ employee records, active lists       │
  │ MEDIUM    │  3600 s    │  300 s    │ dept, desig, roles, permissions      │
  │ PERMANENT │ 86400 s    │ 3600 s    │ Slack UIDs, status codes             │
  └───────────┴────────────┴───────────┴──────────────────────────────────────┘

L1 is kept much shorter than L2 because L1 cannot be invalidated
across processes — it must auto-expire quickly so stale data does not
linger after a write in another service instance.

Explicit cache_delete() / invalidate_pattern() on every write is still
the primary freshness guarantee. TTL is only the safety net.

Invalidate:
  cache_delete()       → removes exact key from both layers
  invalidate_pattern() → L1 prefix wipe + Redis scan_iter (non-blocking)
"""

import json
import logging
from typing import Any, Optional

from src.notifications.redis_client import get_redis
from src.common.local_cache import lc_get, lc_set, lc_delete, lc_delete_prefix

logger = logging.getLogger(__name__)


# ── TTL tiers — import and use these everywhere ───────────────────────────────
#                             L2 (Redis)    L1 (in-process)
TTL_VOLATILE  = 60   ;  L1_VOLATILE  = 30    
TTL_SHORT     = 300  ;  L1_SHORT     = 60    
TTL_MEDIUM    = 3600 ;  L1_MEDIUM    = 300   
TTL_PERMANENT = 86400;  L1_PERMANENT = 3600  


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def cache_get(key: str, l1_ttl: int = L1_SHORT) -> Optional[Any]:
    """
    L1 → L2 read.
    Returns deserialised value, or None on full miss / error.

    l1_ttl: how long to keep the value in L1 when back-filling from Redis.
            Pass the matching L1_* constant for the data type (default: L1_SHORT).
    """
    # ── L1 ──────────────────────────────────────────────────────────────────
    hit = lc_get(key)
    if hit is not None:
        return hit

    # ── L2 (Redis) ──────────────────────────────────────────────────────────
    try:
        r = get_redis()
        raw = await r.get(key)
        if raw is None:
            return None
        value = json.loads(raw)
        lc_set(key, value, ttl=l1_ttl)
        return value
    except Exception as exc:
        logger.warning("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int = TTL_SHORT, l1_ttl: int = L1_SHORT) -> bool:
    """
    Write to Redis (L2) then populate L1.

    ttl:    Redis expiry in seconds   — use a TTL_* constant.
    l1_ttl: L1 expiry in seconds      — use the matching L1_* constant.
    Default tier: SHORT (TTL_SHORT / L1_SHORT).

    Returns True on success, False on Redis error (L1 is still populated).
    """
    serialised = json.dumps(value, default=str)

    # ── L2 (Redis) ──────────────────────────────────────────────────────────
    ok = False
    try:
        r = get_redis()
        await r.setex(key, ttl, serialised)
        ok = True
    except Exception as exc:
        logger.warning("cache_set(%s) failed: %s", key, exc)

    # ── L1 — always populate even if Redis failed ────────────────────────────
    lc_set(key, value, ttl=l1_ttl)
    return ok


async def cache_delete(*keys: str) -> None:
    if not keys:
        return

    for key in keys:
        lc_delete(key)

    try:
        r = get_redis()
        await r.delete(*keys)
        logger.debug("cache_delete: removed keys=%s", keys)
    except RuntimeError:
        logger.debug("cache_delete%s skipped — Redis not ready yet", keys)
    except Exception as exc:
        logger.warning("cache_delete%s failed: %s", keys, exc)


async def invalidate_pattern(pattern: str) -> int:
    """
    Delete all keys matching a glob pattern.

    L1: strips the trailing '*' and does a prefix wipe (instant).
    L2: uses scan_iter() — non-blocking, safe for production.

    Returns the number of Redis keys deleted. Errors are swallowed.

    Example patterns:
        "dashboard:team:*"
        "org:departments:*"
        "rewards:history:*"
    """
    # ── L1 prefix wipe ───────────────────────────────────────────────────────
    prefix = pattern.rstrip("*")
    lc_delete_prefix(prefix)

    # ── L2 Redis scan ────────────────────────────────────────────────────────
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