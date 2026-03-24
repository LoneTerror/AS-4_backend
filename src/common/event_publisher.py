"""
src/common/event_publisher.py
──────────────────────────────
Fire-and-forget Redis Stream publisher used by all services.

Stream name convention:  events:<domain>.<verb>
  events:employee.created   Auth        -> Wallet
  events:review.created     Recognition -> Wallet

All values in `fields` must be strings (Redis Stream requirement).
`occurred_at` is injected automatically.
Failures are logged as warnings — they never raise so the caller's
own DB transaction is not affected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_STREAM_MAXLEN = 10_000   # approximate cap — avoids unbounded memory growth


async def publish(stream: str, fields: dict[str, str]) -> None:
    """
    XADD `fields` to `stream`.

    Parameters
    ----------
    stream : str   — e.g. 'events:review.created'
    fields : dict  — all values must be strings
    """
    try:
        from src.notifications.redis_client import get_redis
        r = get_redis()

        if "occurred_at" not in fields:
            fields = {**fields, "occurred_at": datetime.now(timezone.utc).isoformat()}

        await r.xadd(stream, fields, maxlen=_STREAM_MAXLEN, approximate=True)
        print(f"PUBLISHED OK → {stream} fields={list(fields.keys())}", flush=True)
        logger.debug("Published %s: %s", stream, fields)

    except RuntimeError as exc:
        print(f"PUBLISH FAILED (RuntimeError) → {stream}: {exc}", flush=True)
        logger.warning("publish(%s): Redis not initialised — event dropped", stream)
    except Exception as exc:
        print(f"PUBLISH FAILED (Exception) → {stream}: {type(exc).__name__}: {exc}", flush=True)
        logger.warning("publish(%s) failed: %s — event dropped", stream, exc)