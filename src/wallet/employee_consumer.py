"""
src/wallet/employee_consumer.py
────────────────────────────────
Redis Stream consumer — listens on 'events:employee.created'
and provisions a wallet for each new employee.

Replaces the wallet creation that was previously done inside
src/auth/service.py — that was a cross-domain write violation.

Consumer group : wallet-service
Consumer name  : employee-wallet-worker-1
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STREAM_KEY    = "events:employee.created"
GROUP_NAME    = "wallet-service"
CONSUMER_NAME = "employee-wallet-worker-1"
BLOCK_MS      = 5_000
BATCH_SIZE    = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_group(r) -> None:
    try:
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
        logger.info("Consumer group '%s' created on '%s'", GROUP_NAME, STREAM_KEY)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _provision_wallet(employee_id: str, created_by: str) -> None:
    """Create a wallet if one doesn't already exist — idempotent."""
    from src.prisma.client import db
    existing = await db.wallets.find_first(where={"employee_id": employee_id})
    if existing:
        logger.debug("Wallet already exists for %s", employee_id)
        return
    await db.wallets.create(data={
        "employee_id":         employee_id,
        "available_points":    0,
        "redeemed_points":     0,
        "total_earned_points": 0,
        "created_by":          created_by,
        "updated_by":          created_by,
        "updated_at":          _now(),
    })
    logger.info("Wallet provisioned for employee %s", employee_id)


async def employee_created_consumer_loop(shutdown_event: asyncio.Event) -> None:
    from src.notifications.redis_client import get_redis
    try:
        r = get_redis()
    except RuntimeError:
        logger.warning("Redis unavailable — employee.created consumer disabled")
        return

    await _ensure_group(r)
    await _recover_pending(r)
    logger.info("employee.created consumer started")

    while not shutdown_event.is_set():
        try:
            results = await r.xreadgroup(
                groupname=GROUP_NAME,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=BATCH_SIZE,
                block=BLOCK_MS,
            )
            if not results:
                continue
            for _stream, messages in results:
                for msg_id, fields in messages:
                    await _handle_message(r, msg_id, fields)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("employee.created consumer error: %s", exc)
            if "NOGROUP" in str(exc):
                try:
                    await _ensure_group(r)
                except Exception as eg_exc:
                    logger.error("employee.created _ensure_group recovery failed: %s", eg_exc)
            await asyncio.sleep(2)

    logger.info("employee.created consumer stopped")


async def _recover_pending(r) -> None:
    try:
        pending = await r.xpending_range(
            STREAM_KEY, GROUP_NAME, min="-", max="+", count=100,
        )
        if not pending:
            return
        logger.info("Recovering %d pending employee.created messages", len(pending))
        for entry in pending:
            msg_id = entry["message_id"]
            msgs   = await r.xrange(STREAM_KEY, min=msg_id, max=msg_id)
            if msgs:
                _, fields = msgs[0]
                await _handle_message(r, msg_id, fields)
    except Exception as exc:
        logger.warning("employee.created pending recovery failed: %s", exc)


async def _handle_message(r, msg_id: str, fields: dict) -> None:
    employee_id = fields.get("employee_id", "")
    created_by  = fields.get("created_by", "system")
    if not employee_id:
        logger.warning("employee.created msg %s missing employee_id", msg_id)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        return
    try:
        await _provision_wallet(employee_id, created_by)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except Exception as exc:
        logger.error("Failed to provision wallet for %s: %s", employee_id, exc)