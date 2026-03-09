"""
src/common/local_cache.py
──────────────────────────
Ultra-fast in-process (L1) cache — pure Python dict, zero network cost.

Used as the first layer in front of Redis. Every cache_get() checks
here before touching Redis. TTLs are shorter than Redis so data
stays reasonably fresh without needing Redis round-trips.

Thread/async safety: asyncio is single-threaded per event loop,
so plain dict reads/writes are safe with no locking needed.
"""

import time
from typing import Any

# { key: (value, expire_at_monotonic_seconds) }
_store: dict[str, tuple[Any, float]] = {}


def lc_get(key: str) -> Any | None:
    """Return cached value or None if missing/expired."""
    entry = _store.get(key)
    if entry is None:
        return None
    value, expire_at = entry
    if time.monotonic() < expire_at:
        return value
    del _store[key]   # lazy eviction on access
    return None


def lc_set(key: str, value: Any, ttl: int = 30) -> None:
    """Store value with TTL in seconds."""
    _store[key] = (value, time.monotonic() + ttl)


def lc_delete(key: str) -> None:
    """Remove a single key."""
    _store.pop(key, None)


def lc_delete_prefix(prefix: str) -> None:
    """Remove all keys starting with prefix (mirrors invalidate_pattern glob logic)."""
    to_delete = [k for k in _store if k.startswith(prefix)]
    for k in to_delete:
        del _store[k]


def lc_clear() -> None:
    """Wipe entire local cache. Useful in tests."""
    _store.clear()


def lc_size() -> int:
    """Current number of entries (includes not-yet-evicted expired ones)."""
    return len(_store)