# src/notifications/cache.py
"""
Redis cache helpers.

Keys & TTLs
───────────────────────────────────────────────────────────────
  notify:pending                  List  – notification_id queue (no TTL, drained by worker)
  notify:recovery_done            String – set at startup after recovery scan (24h TTL)

  cache:employee:<id>             Hash  – employee fields          TTL 10 min
  cache:employees:active          String (JSON list of ids)        TTL 60 min
  cache:employees:active:<dept>   String (JSON list of ids)        TTL 60 min

  cache:dept:<code>               String (dept JSON)               TTL 6 h
  cache:desig:<code>              String (desig JSON)              TTL 6 h
  cache:status:<code>             String (status_id UUID)          TTL 6 h

  cache:slack:uid:<email>         String (slack user id or "")     TTL 24 h
  cache:celebration:active_emps   String (JSON employee list)      TTL 60 min
───────────────────────────────────────────────────────────────
All helpers gracefully fall back to DB on any Redis error so a
Redis outage never breaks the critical path.

L1 (in-process) layer
───────────────────────────────────────────────────────────────
Hot read-heavy keys (employee, dept, desig, status, Slack UID,
celebration list) are also stored in a local Python dict with a
shorter TTL so repeated lookups within the same process never
touch Redis.

Queue operations (LPUSH / BRPOP on notify:pending) intentionally
bypass L1 — they need real-time Redis list semantics.
───────────────────────────────────────────────────────────────
"""

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── TTLs (L2 = Redis) ─────────────────────────────────────────────────────────
TTL_EMPLOYEE      = 600       # 10 min
TTL_ACTIVE_LIST   = 3600      # 1 h
TTL_LOOKUP        = 21_600    # 6 h  (dept / desig / status — rarely change)
TTL_SLACK_UID     = 86_400    # 24 h
TTL_CELEB_EMPS    = 3600      # 1 h

# ── Queue key ─────────────────────────────────────────────────────────────────
QUEUE_KEY = "notify:pending"


# ─────────────────────────────────────────────────────────────────────────────
# L1 — in-process cache (zero Redis round-trip)
# ─────────────────────────────────────────────────────────────────────────────
# Stored separately from src/common/local_cache.py so this module has
# no import dependency on the common package (notifications is lower-level).

# L1 TTLs — intentionally shorter than L2 so stale data auto-expires
_L1_TTL_EMPLOYEE   = 60    # 1 min  (TTL_EMPLOYEE  = 10 min)
_L1_TTL_ACTIVE     = 120   # 2 min  (TTL_ACTIVE_LIST = 1 h)
_L1_TTL_LOOKUP     = 300   # 5 min  (TTL_LOOKUP = 6 h)
_L1_TTL_SLACK      = 600   # 10 min (TTL_SLACK_UID = 24 h)
_L1_TTL_CELEB      = 120   # 2 min  (TTL_CELEB_EMPS = 1 h)

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
# Employee cache  (L1 + L2)
# ─────────────────────────────────────────────────────────────────────────────

def _emp_key(employee_id: str) -> str:
    return f"cache:employee:{employee_id}"


async def get_cached_employee(r: aioredis.Redis, employee_id: str) -> dict | None:
    key = _emp_key(employee_id)

    # L1
    hit = _l1_get(key)
    if hit is not None:
        return hit

    # L2
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, _L1_TTL_EMPLOYEE)
        return value
    except Exception:
        return None


async def set_cached_employee(r: aioredis.Redis, employee_id: str, emp_dict: dict) -> None:
    key = _emp_key(employee_id)
    # L2
    try:
        await r.setex(key, TTL_EMPLOYEE, json.dumps(emp_dict))
    except Exception:
        pass
    # L1 — always populate
    _l1_set(key, emp_dict, _L1_TTL_EMPLOYEE)


async def invalidate_employee(r: aioredis.Redis, employee_id: str) -> None:
    """Call this from webhook handlers when an employee record changes."""
    key = _emp_key(employee_id)

    # L1
    _l1_delete(key)
    _l1_delete_prefix("cache:employees:active")   # active list may include this employee

    # L2
    try:
        await r.delete(key)
        # Bust active-employee list caches since membership may have changed
        async for active_key in r.scan_iter("cache:employees:active*"):
            await r.delete(active_key)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Active employee list cache  (L1 + L2)
# ─────────────────────────────────────────────────────────────────────────────

def _active_key(dept_id: str | None) -> str:
    return f"cache:employees:active:{dept_id}" if dept_id else "cache:employees:active"


async def get_cached_active_employee_ids(
    r: aioredis.Redis, dept_id: str | None = None
) -> list[str] | None:
    key = _active_key(dept_id)

    # L1
    hit = _l1_get(key)
    if hit is not None:
        return hit

    # L2
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, _L1_TTL_ACTIVE)
        return value
    except Exception:
        return None


async def set_cached_active_employee_ids(
    r: aioredis.Redis, ids: list[str], dept_id: str | None = None
) -> None:
    key = _active_key(dept_id)
    try:
        await r.setex(key, TTL_ACTIVE_LIST, json.dumps(ids))
    except Exception:
        pass
    _l1_set(key, ids, _L1_TTL_ACTIVE)


# ─────────────────────────────────────────────────────────────────────────────
# Celebration employee list cache  (L1 + L2)
# ─────────────────────────────────────────────────────────────────────────────

CELEB_EMPS_KEY = "cache:celebration:active_emps"


async def get_cached_celebration_employees(r: aioredis.Redis) -> list[dict] | None:
    # L1
    hit = _l1_get(CELEB_EMPS_KEY)
    if hit is not None:
        return hit

    # L2
    try:
        data = await r.get(CELEB_EMPS_KEY)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(CELEB_EMPS_KEY, value, _L1_TTL_CELEB)
        return value
    except Exception:
        return None


async def set_cached_celebration_employees(r: aioredis.Redis, employees: list[dict]) -> None:
    try:
        await r.setex(CELEB_EMPS_KEY, TTL_CELEB_EMPS, json.dumps(employees))
    except Exception:
        pass
    _l1_set(CELEB_EMPS_KEY, employees, _L1_TTL_CELEB)


# ─────────────────────────────────────────────────────────────────────────────
# Lookup caches — dept / desig / status  (L1 + L2)
# ─────────────────────────────────────────────────────────────────────────────

async def get_cached_lookup(r: aioredis.Redis, key: str) -> Any | None:
    # L1
    hit = _l1_get(key)
    if hit is not None:
        return hit

    # L2
    try:
        data = await r.get(key)
        if data is None:
            return None
        value = json.loads(data)
        _l1_set(key, value, _L1_TTL_LOOKUP)
        return value
    except Exception:
        return None


async def set_cached_lookup(r: aioredis.Redis, key: str, value: Any) -> None:
    try:
        await r.setex(key, TTL_LOOKUP, json.dumps(value))
    except Exception:
        pass
    _l1_set(key, value, _L1_TTL_LOOKUP)


def dept_key(code: str)   -> str: return f"cache:dept:{code}"
def desig_key(code: str)  -> str: return f"cache:desig:{code}"
def status_key(code: str) -> str: return f"cache:status:{code}"


# ─────────────────────────────────────────────────────────────────────────────
# Slack UID cache  (L1 + L2)
# ─────────────────────────────────────────────────────────────────────────────

def _slack_uid_key(email: str) -> str:
    return f"cache:slack:uid:{email.lower()}"

_SLACK_NOT_FOUND = "__NOT_FOUND__"   # sentinel so we cache "no user" too


async def get_cached_slack_uid(r: aioredis.Redis, email: str) -> str | None | bool:
    """
    Returns:
      str   – the Slack user ID
      ""    – cached "not found" (don't call Slack again)
      None  – cache miss (call Slack)
    """
    key = _slack_uid_key(email)

    # L1
    hit = _l1_get(key)
    if hit is not None:
        return "" if hit == _SLACK_NOT_FOUND else hit

    # L2
    try:
        data = await r.get(key)
        if data is None:
            return None
        _l1_set(key, data, _L1_TTL_SLACK)
        if data == _SLACK_NOT_FOUND:
            return ""
        return data
    except Exception:
        return None


async def set_cached_slack_uid(r: aioredis.Redis, email: str, uid: str | None) -> None:
    key = _slack_uid_key(email)
    value = uid if uid else _SLACK_NOT_FOUND
    try:
        await r.setex(key, TTL_SLACK_UID, value)
    except Exception:
        pass
    _l1_set(key, value, _L1_TTL_SLACK)