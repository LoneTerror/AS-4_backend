"""
src/analytics/reward_consumer.py
──────────────────────────────────
Redis Stream consumer — listens on 'events:reward.redeemed'
and invalidates the analytics leaderboard cache.

Each time a reward is redeemed, the leaderboard data is stale and
needs to be cleared so the next request fetches fresh data.

Consumer group : analytics-service
Consumer name  : leaderboard-invalidator-1
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

STREAM_KEY    = "events:reward.redeemed"
GROUP_NAME    = "analytics-service"
CONSUMER_NAME = "leaderboard-invalidator-1"
BLOCK_MS      = 5_000
BATCH_SIZE    = 10


async def _ensure_group(r) -> None:
    try:
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def reward_redeemed_consumer_loop(shutdown_event: asyncio.Event) -> None:
    from src.notifications.redis_client import get_redis
    try:
        r = get_redis()
    except RuntimeError:
        logger.warning("Redis unavailable — analytics reward.redeemed consumer disabled")
        return

    await _ensure_group(r)
    await _recover_pending(r)
    logger.info("analytics reward.redeemed consumer started")

    while not shutdown_event.is_set():
        try:
            results = await r.xreadgroup(
                groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"}, count=BATCH_SIZE, block=BLOCK_MS,
            )
            if not results:
                continue
            for _stream, messages in results:
                for msg_id, fields in messages:
                    await _handle_message(r, msg_id, fields)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("analytics reward.redeemed consumer error: %s", exc)
            if "NOGROUP" in str(exc):
                try:
                    await _ensure_group(r)
                except Exception as eg_exc:
                    logger.error("analytics reward.redeemed _ensure_group recovery failed: %s", eg_exc)
            await asyncio.sleep(2)

    logger.info("analytics reward.redeemed consumer stopped")


async def _recover_pending(r) -> None:
    try:
        pending = await r.xpending_range(STREAM_KEY, GROUP_NAME, min="-", max="+", count=100)
        if not pending:
            return
        for entry in pending:
            msg_id = entry["message_id"]
            msgs   = await r.xrange(STREAM_KEY, min=msg_id, max=msg_id)
            if msgs:
                _, fields = msgs[0]
                await _handle_message(r, msg_id, fields)
    except Exception as exc:
        logger.warning("analytics reward.redeemed recovery failed: %s", exc)


async def _handle_message(r, msg_id: str, fields: dict) -> None:
    history_id = fields.get("history_id", "unknown")
    try:
        from .service import invalidate_leaderboard
        await invalidate_leaderboard()
        logger.debug("Leaderboard cache invalidated for redemption %s", history_id)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except Exception as exc:
        logger.error("Failed to invalidate leaderboard for redemption %s: %s", history_id, exc)