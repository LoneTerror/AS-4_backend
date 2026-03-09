"""
src/common/cache.py
────────────────────
Two-layer cache:
  L1 — in-process Python dict  (0ms, process-local, short TTL)
  L2 — Redis                   (~1ms local / ~55ms remote, longer TTL)

Read path:
  1. Check L1 → return immediately on hit (zero Redis round-trip)
  2. Check Redis → back-fill L1 → return on hit
  3. Return None on full miss (caller queries DB)

Write path:
  1. Write Redis (setex)
  2. Populate L1 with a shorter TTL

Invalidate:
  cache_delete()       → removes exact key from both layers
  invalidate_pattern() → L1 prefix wipe + Redis scan_iter (non-blocking)

Everything else is unchanged from the original implementation —
same function signatures, same error handling, same import path.
"""

import json
import logging
from typing import Any, Optional

from src.notifications.redis_client import get_redis
from src.common.local_cache import lc_get, lc_set, lc_delete, lc_delete_prefix

logger = logging.getLogger(__name__)


# ── L1 TTL strategy ───────────────────────────────────────────────────────────
# L1 TTL is a fraction of L2 TTL so the local cache auto-refreshes
# from Redis periodically, keeping multi-process deployments consistent.

def _l1_ttl(l2_ttl: int) -> int:
    """
    Return an appropriate L1 TTL given the Redis TTL.

    L2 TTL       L1 TTL   Rationale
    ─────────    ───────  ─────────────────────────────────────────
    ≤ 30s          5s     Very volatile — wallet balances etc.
    ≤ 120s        15s     Volatile — personal history
    ≤ 600s        30s     Semi-static — paginated lists
    ≤ 3600s       60s     Static-ish — roles, permissions, org data
    > 3600s      120s     Near-permanent — Slack UIDs, dept lookups
    """
    if l2_ttl <= 30:
        return 5
    if l2_ttl <= 120:
        return 15
    if l2_ttl <= 600:
        return 30
    if l2_ttl <= 3600:
        return 60
    return 120


# ─────────────────────────────────────────────────────────────────────────────
# Public API  (same signatures as before — drop-in replacement)
# ─────────────────────────────────────────────────────────────────────────────

async def cache_get(key: str) -> Optional[Any]:
    """
    L1 → L2 read.
    Returns deserialised value, or None on full miss / error.
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
        # Back-fill L1 — use a medium TTL since we don't know the original L2 TTL here
        lc_set(key, value, ttl=30)
        return value
    except Exception as exc:
        logger.warning("cache_get(%s) failed: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int = 60) -> bool:
    """
    Write to Redis (L2) then populate L1.
    ttl is the Redis expiry in seconds.
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
    lc_set(key, value, ttl=_l1_ttl(ttl))
    return ok


async def cache_delete(*keys: str) -> None:
    """
    Delete one or more exact keys from both layers.
    Errors are swallowed.
    """
    if not keys:
        return

    # ── L1 ──────────────────────────────────────────────────────────────────
    for key in keys:
        lc_delete(key)

    # ── L2 (Redis) ──────────────────────────────────────────────────────────
    try:
        r = get_redis()
        await r.delete(*keys)
        logger.debug("cache_delete: removed keys=%s", keys)
    except Exception as exc:
        logger.warning("cache_delete%s failed: %s", keys, exc)


async def invalidate_pattern(pattern: str) -> int:
    """
    Delete all keys matching a glob pattern.

    L1: strips the trailing '*' and does a prefix wipe (instant).
    L2: uses scan_iter() — non-blocking, safe for production.

    Returns the number of Redis keys deleted.
    Errors are swallowed.

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