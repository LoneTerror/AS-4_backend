"""
src/wallet/review_consumer.py
──────────────────────────────
Redis Stream consumer — listens on 'events:review.created'
and credits points to the receiver's wallet.

Previously the Recognition service called POST /v1/wallets/credit-from-review
synchronously.  That endpoint is now DEPRECATED.  This consumer replaces it:

  Recognition service  →  XADD events:review.created
  Wallet service       ←  XREADGROUP (this file)  →  db.wallets / db.transactions

Idempotency
───────────
Each message carries a review_id.  Before crediting, we check if a
transaction with reference_number = review_id already exists.
If yes, we ACK and skip.  This makes re-delivery safe.

Consumer group : wallet-service
Consumer name  : review-credit-worker-1
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STREAM_KEY    = "events:review.created"
GROUP_NAME    = "wallet-service"
CONSUMER_NAME = "review-credit-worker-1"
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


async def _credit_points(review_id: str, receiver_id: str, raw_points: int) -> None:
    """
    Credit raw_points to the receiver's wallet.
    Idempotent — skips if a transaction for this review_id already exists.
    """
    from src.prisma.client import db

    # ── Idempotency check ─────────────────────────────────────────────────────
    existing_txn = await db.transactions.find_first(
        where={"reference_number": review_id}
    )
    if existing_txn:
        logger.debug("Transaction for review %s already exists — skipping", review_id)
        return

    # ── Find wallet ───────────────────────────────────────────────────────────
    wallet = await db.wallets.find_first(where={"employee_id": receiver_id})
    if not wallet:
        # Wallet not yet created — it may still be in-flight from employee.created.
        # Raise so the message stays pending and is retried.
        raise RuntimeError(f"Wallet not found for employee {receiver_id}")

    # ── Resolve CREDIT transaction type ───────────────────────────────────────
    credit_type = await db.transaction_types.find_first(
        where={"is_credit": True, "type_code": "REVIEW_CREDIT"}
    )
    if not credit_type:
        # Fall back to any credit type
        credit_type = await db.transaction_types.find_first(where={"is_credit": True})
    if not credit_type:
        raise RuntimeError("No credit transaction type found in transaction_types table")

    # ── Resolve SUCCESS status ────────────────────────────────────────────────
    status = await db.status_master.find_first(
        where={"status_code": "SUCCESS", "entity_type": "TRANSACTION"}
    )
    if not status:
        status = await db.status_master.find_first(where={"status_code": "SUCCESS"})
    if not status:
        raise RuntimeError("No SUCCESS status found in status_master table")

    # ── Write transaction + update wallet atomically via Prisma ──────────────
    # Prisma doesn't expose raw transactions via the Python client's batch API
    # in the same way — we use sequential writes with the idempotency guard
    # above as our safety net.
    await db.transactions.create(data={
        "wallet_id":           wallet.wallet_id,
        "amount":              raw_points,
        "transaction_type_id": credit_type.type_id,
        "status_id":           status.status_id,
        "reference_number":    review_id,
        "description":         f"Points credited from review {review_id}",
        "transaction_at":      _now(),
        "created_by":          receiver_id,
        "updated_by":          receiver_id,
        "updated_at":          _now(),
    })

    await db.wallets.update(
        where={"wallet_id": wallet.wallet_id},
        data={
            "available_points":    {"increment": raw_points},
            "total_earned_points": {"increment": raw_points},
            "updated_by":          receiver_id,
            "updated_at":          _now(),
        },
    )

    logger.info(
        "Credited %d points to wallet %s for review %s",
        raw_points, wallet.wallet_id, review_id,
    )


async def review_created_consumer_loop(shutdown_event: asyncio.Event) -> None:
    """
    Long-running coroutine — start as asyncio.Task in Wallet service lifespan.
    """
    from src.notifications.redis_client import get_redis
    try:
        r = get_redis()
    except RuntimeError:
        logger.warning("Redis not available — review.created consumer disabled")
        return

    await _ensure_group(r)
    await _recover_pending(r)
    logger.info("review.created consumer started")

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
            logger.error("review.created consumer error: %s", exc)
            if "NOGROUP" in str(exc):
                # Stream or consumer group was deleted (e.g. Redis flush/restart).
                # Re-create the group so the next iteration can proceed.
                try:
                    await _ensure_group(r)
                except Exception as eg_exc:
                    logger.error("review.created _ensure_group recovery failed: %s", eg_exc)
            await asyncio.sleep(2)

    logger.info("review.created consumer stopped")


async def _recover_pending(r) -> None:
    try:
        pending = await r.xpending_range(
            STREAM_KEY, GROUP_NAME, min="-", max="+", count=100,
        )
        if not pending:
            return
        logger.info("Recovering %d pending review.created messages", len(pending))
        for entry in pending:
            msg_id = entry["message_id"]
            msgs   = await r.xrange(STREAM_KEY, min=msg_id, max=msg_id)
            if msgs:
                _, fields = msgs[0]
                await _handle_message(r, msg_id, fields)
    except Exception as exc:
        logger.warning("review.created pending recovery failed: %s", exc)


async def _handle_message(r, msg_id: str, fields: dict) -> None:
    review_id   = fields.get("review_id", "")
    receiver_id = fields.get("receiver_id", "")
    try:
        raw_points = int(fields.get("raw_points", "0"))
    except ValueError:
        raw_points = 0

    if not review_id or not receiver_id:
        logger.warning("review.created msg %s missing fields — ACKing", msg_id)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        return

    try:
        await _credit_points(review_id, receiver_id, raw_points)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except Exception as exc:
        # Log but don't ACK — message stays pending for next recovery pass.
        # After several retries consider moving to a dead-letter stream.
        logger.error(
            "Failed to credit review %s to employee %s: %s",
            review_id, receiver_id, exc,
        )