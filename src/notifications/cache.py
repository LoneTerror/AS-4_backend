# src/notifications/cache.py
"""
Redis cache helpers for the notifications service.

Keys & TTLs — all use the shared tier system:
───────────────────────────────────────────────────────────────
  notify:pending                  List  – notification_id queue (no TTL, drained by worker)
  notify:recovery_done            String – set at startup after recovery scan (PERMANENT)

  cache:employee:<id>             Employee fields          SHORT     (L2: 300s  / L1: 60s)
  cache:employees:active          JSON list of ids         SHORT     (L2: 300s  / L1: 60s)
  cache:employees:active:<dept>   JSON list of ids         SHORT     (L2: 300s  / L1: 60s)
  cache:celebration:active_emps   JSON employee list       SHORT     (L2: 300s  / L1: 60s)

  cache:dept:<code>               dept JSON                MEDIUM    (L2: 3600s / L1: 300s)
  cache:desig:<code>              desig JSON               MEDIUM    (L2: 3600s / L1: 300s)
  cache:status:<code>             status_id UUID           MEDIUM    (L2: 3600s / L1: 300s)

  cache:slack:uid:<email>         slack user id or ""      PERMANENT (L2: 86400s / L1: 3600s)
───────────────────────────────────────────────────────────────

TTL TIERS (same as src/common/cache.py — one system everywhere):
  VOLATILE  → L2:   60s  / L1:   30s  — wallet balance, unread counts
  SHORT     → L2:  300s  / L1:   60s  — employee records, active lists
  MEDIUM    → L2: 3600s  / L1:  300s  — dept, desig, roles, permissions
  PERMANENT → L2: 86400s / L1: 3600s  — Slack UIDs, status codes

L1 is kept much shorter than L2 because it cannot be invalidated
across processes — it must auto-expire quickly after a write elsewhere.
Explicit invalidation on writes is still the primary freshness guarantee.

Queue operations (LPUSH / BRPOP on notify:pending) bypass L1 entirely —
they need real-time Redis list semantics.
───────────────────────────────────────────────────────────────
"""

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# ── TTL tiers — same values as src/common/cache.py ───────────────────────────
#                             L2 (Redis)    L1 (in-process)
TTL_VOLATILE  = 60   ;  L1_VOLATILE  = 30    # wallet balance, unread counts
TTL_SHORT     = 300  ;  L1_SHORT     = 60    # employee records, active lists
TTL_MEDIUM    = 3600 ;  L1_MEDIUM    = 300   # dept, desig, roles, permissions
TTL_PERMANENT = 86400;  L1_PERMANENT = 3600  # Slack UIDs, status codes

# ── Queue key ─────────────────────────────────────────────────────────────────
QUEUE_KEY = "notify:pending"


# ─────────────────────────────────────────────────────────────────────────────
# L1 — in-process cache (zero Redis round-trip)
# ─────────────────────────────────────────────────────────────────────────────
# Kept separate from src/common/local_cache.py — notifications is a lower-level
# service and should not import from common to avoid circular dependencies.

# { key: (value, expire_at_monotonic) }
_l1: dict[str, tuple[Any, float]] = {}


def _l1_get(key: str) -> Any | None:
    entry = _l1.get(key)
    if entry is None:
        return None
    value, expire_at = entry
    if time.monotonic() < expire_at:
        return value
    del _l1[key]
    return None


def _l1_set(key: str, value: Any, ttl: int) -> None:
    _l1[key] = (value, time.monotonic() + ttl)


def _l1_delete(key: str) -> None:
    _l1.pop(key, None)


def _l1_delete_prefix(prefix: str) -> None:
    to_delete = [k for k in _l1 if k.startswith(prefix)]
    for k in to_delete:
        del _l1[k]


# ─────────────────────────────────────────────────────────────────────────────
# Queue helpers  (NO L1 — need real-time Redis list semantics)
# ─────────────────────────────────────────────────────────────────────────────

async def enqueue_notification(r: aioredis.Redis, notification_id: str) -> None:
    """Push a notification ID onto the work queue. Fire-and-forget."""
    try:
        await r.lpush(QUEUE_KEY, notification_id)
    except Exception:
        logger.warning("Redis enqueue failed for %s — worker will recover on next scan", notification_id)


async def dequeue_notification(r: aioredis.Redis, timeout: int = 5) -> str | None:
    """
    Blocking pop — returns a notification_id or None on timeout.
    timeout=5 means the worker wakes up at least every 5s to check for shutdown.
    """
    try:
        result = await r.brpop(QUEUE_KEY, timeout=timeout)
        if result:
            _key, value = result
            return value
        return None
    except Exception:
        logger.warning("Redis BRPOP failed — falling back to DB scan mode")
        return None


async def queue_length(r: aioredis.Redis) -> int:
    try:
        return await r.llen(QUEUE_KEY)
    except Exception:
        return -1


# ─────────────────────────────────────────────────────────────────────────────
# Employee cache  — SHORT tier (L2: 300s / L1: 60s)
# ─────────────────────────────────────────────────────────────────────────────

def _emp_key(employee_id: str) -> str:
    return f"cache:employee:{employee_id}"


async def get_cached_employee(r: aioredis.Redis, employee_id: str) -> dict | None:
    key = _emp_key(employee_id)
    hit = _l1_get(key)
    if hit is not None:
        return hit
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, L1_SHORT)
        return value
    except Exception:
        return None


async def set_cached_employee(r: aioredis.Redis, employee_id: str, emp_dict: dict) -> None:
    key = _emp_key(employee_id)
    try:
        await r.setex(key, TTL_SHORT, json.dumps(emp_dict))
    except Exception:
        pass
    _l1_set(key, emp_dict, L1_SHORT)


async def invalidate_employee(r: aioredis.Redis, employee_id: str) -> None:
    """Call this from webhook handlers when an employee record changes."""
    key = _emp_key(employee_id)
    _l1_delete(key)
    _l1_delete_prefix("cache:employees:active")
    try:
        await r.delete(key)
        async for active_key in r.scan_iter("cache:employees:active*"):
            await r.delete(active_key)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Active employee list cache  — SHORT tier (L2: 300s / L1: 60s)
# ─────────────────────────────────────────────────────────────────────────────

def _active_key(dept_id: str | None) -> str:
    return f"cache:employees:active:{dept_id}" if dept_id else "cache:employees:active"


async def get_cached_active_employee_ids(
    r: aioredis.Redis, dept_id: str | None = None
) -> list[str] | None:
    key = _active_key(dept_id)
    hit = _l1_get(key)
    if hit is not None:
        return hit
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, L1_SHORT)
        return value
    except Exception:
        return None


async def set_cached_active_employee_ids(
    r: aioredis.Redis, ids: list[str], dept_id: str | None = None
) -> None:
    key = _active_key(dept_id)
    try:
        await r.setex(key, TTL_SHORT, json.dumps(ids))
    except Exception:
        pass
    _l1_set(key, ids, L1_SHORT)


# ─────────────────────────────────────────────────────────────────────────────
# Celebration employee list cache  — SHORT tier (L2: 300s / L1: 60s)
# ─────────────────────────────────────────────────────────────────────────────

CELEB_EMPS_KEY = "cache:celebration:active_emps"


async def get_cached_celebration_employees(r: aioredis.Redis) -> list[dict] | None:
    hit = _l1_get(CELEB_EMPS_KEY)
    if hit is not None:
        return hit
    try:
        data = await r.get(CELEB_EMPS_KEY)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(CELEB_EMPS_KEY, value, L1_SHORT)
        return value
    except Exception:
        return None


async def set_cached_celebration_employees(r: aioredis.Redis, employees: list[dict]) -> None:
    try:
        await r.setex(CELEB_EMPS_KEY, TTL_SHORT, json.dumps(employees))
    except Exception:
        pass
    _l1_set(CELEB_EMPS_KEY, employees, L1_SHORT)


# ─────────────────────────────────────────────────────────────────────────────
# Lookup caches — dept / desig / status  — MEDIUM tier (L2: 3600s / L1: 300s)
# ─────────────────────────────────────────────────────────────────────────────

async def get_cached_lookup(r: aioredis.Redis, key: str) -> Any | None:
    hit = _l1_get(key)
    if hit is not None:
        return hit
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, L1_MEDIUM)
        return value
    except Exception:
        return None


async def set_cached_lookup(r: aioredis.Redis, key: str, value: Any) -> None:
    try:
        await r.setex(key, TTL_MEDIUM, json.dumps(value))
    except Exception:
        pass
    _l1_set(key, value, L1_MEDIUM)


def dept_key(code: str)   -> str: return f"cache:dept:{code}"
def desig_key(code: str)  -> str: return f"cache:desig:{code}"
def status_key(code: str) -> str: return f"cache:status:{code}"


# ─────────────────────────────────────────────────────────────────────────────
# Slack UID cache  — PERMANENT tier (L2: 86400s / L1: 3600s)
# ─────────────────────────────────────────────────────────────────────────────

def _slack_uid_key(email: str) -> str:
    return f"cache:slack:uid:{email.lower()}"

_SLACK_NOT_FOUND = "__NOT_FOUND__"   # sentinel so we cache "no user" too


async def get_cached_slack_uid(r: aioredis.Redis, email: str) -> str | None:
    """
    Returns:
      str   – the Slack user ID
      ""    – cached "not found" (don't call Slack again)
      None  – cache miss (call Slack)
    """
    key = _slack_uid_key(email)
    hit = _l1_get(key)
    if hit is not None:
        return "" if hit == _SLACK_NOT_FOUND else hit
    try:
        data = await r.get(key)
        if data is None:
            return None
        _l1_set(key, data, L1_PERMANENT)
        return "" if data == _SLACK_NOT_FOUND else data
    except Exception:
        return None


async def set_cached_slack_uid(r: aioredis.Redis, email: str, uid: str | None) -> None:
    key = _slack_uid_key(email)
    value = uid if uid else _SLACK_NOT_FOUND
    try:
        await r.setex(key, TTL_PERMANENT, value)
    except Exception:
        pass
    _l1_set(key, value, L1_PERMANENT)