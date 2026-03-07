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
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ── TTLs ──────────────────────────────────────────────────────────────────────
TTL_EMPLOYEE      = 600       # 10 min
TTL_ACTIVE_LIST   = 3600      # 1 h
TTL_LOOKUP        = 21_600    # 6 h  (dept / desig / status — rarely change)
TTL_SLACK_UID     = 86_400    # 24 h
TTL_CELEB_EMPS    = 3600      # 1 h

# ── Queue key ─────────────────────────────────────────────────────────────────
QUEUE_KEY = "notify:pending"


# ── Queue helpers ─────────────────────────────────────────────────────────────

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


# ── Employee cache ────────────────────────────────────────────────────────────

def _emp_key(employee_id: str) -> str:
    return f"cache:employee:{employee_id}"


async def get_cached_employee(r: aioredis.Redis, employee_id: str) -> dict | None:
    try:
        data = await r.get(_emp_key(employee_id))
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_cached_employee(r: aioredis.Redis, employee_id: str, emp_dict: dict) -> None:
    try:
        await r.setex(_emp_key(employee_id), TTL_EMPLOYEE, json.dumps(emp_dict))
    except Exception:
        pass


async def invalidate_employee(r: aioredis.Redis, employee_id: str) -> None:
    """Call this from webhook handlers when an employee record changes."""
    try:
        await r.delete(_emp_key(employee_id))
        # Also bust active-employee list caches since membership may have changed
        async for key in r.scan_iter("cache:employees:active*"):
            await r.delete(key)
    except Exception:
        pass


# ── Active employee list cache ─────────────────────────────────────────────────

async def get_cached_active_employee_ids(
    r: aioredis.Redis, dept_id: str | None = None
) -> list[str] | None:
    key = f"cache:employees:active:{dept_id}" if dept_id else "cache:employees:active"
    try:
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_cached_active_employee_ids(
    r: aioredis.Redis, ids: list[str], dept_id: str | None = None
) -> None:
    key = f"cache:employees:active:{dept_id}" if dept_id else "cache:employees:active"
    try:
        await r.setex(key, TTL_ACTIVE_LIST, json.dumps(ids))
    except Exception:
        pass


# ── Celebration employee list cache ──────────────────────────────────────────

CELEB_EMPS_KEY = "cache:celebration:active_emps"


async def get_cached_celebration_employees(r: aioredis.Redis) -> list[dict] | None:
    """
    Returns the full employee list used by the celebration worker (with status join).
    Stored as JSON. None = cache miss.
    """
    try:
        data = await r.get(CELEB_EMPS_KEY)
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_cached_celebration_employees(r: aioredis.Redis, employees: list[dict]) -> None:
    try:
        await r.setex(CELEB_EMPS_KEY, TTL_CELEB_EMPS, json.dumps(employees))
    except Exception:
        pass


# ── Lookup caches (dept / desig / status) ────────────────────────────────────

async def get_cached_lookup(r: aioredis.Redis, key: str) -> Any | None:
    try:
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_cached_lookup(r: aioredis.Redis, key: str, value: Any) -> None:
    try:
        await r.setex(key, TTL_LOOKUP, json.dumps(value))
    except Exception:
        pass


def dept_key(code: str)   -> str: return f"cache:dept:{code}"
def desig_key(code: str)  -> str: return f"cache:desig:{code}"
def status_key(code: str) -> str: return f"cache:status:{code}"


# ── Slack UID cache ───────────────────────────────────────────────────────────

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
    try:
        data = await r.get(_slack_uid_key(email))
        if data is None:
            return None          # cache miss
        if data == _SLACK_NOT_FOUND:
            return ""            # known-absent
        return data
    except Exception:
        return None


async def set_cached_slack_uid(r: aioredis.Redis, email: str, uid: str | None) -> None:
    try:
        value = uid if uid else _SLACK_NOT_FOUND
        await r.setex(_slack_uid_key(email), TTL_SLACK_UID, value)
    except Exception:
        pass