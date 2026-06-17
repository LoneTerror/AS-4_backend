"""
src/wallet/review_consumer.py
──────────────────────────────
Redis Stream consumer — listens on 'events:review.created'
and credits points to the receiver's wallet.

Previously the Recognition service called POST /aabhar/v1/wallets/credit-from-review
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

from src.prisma.client import db
from src.common.audit import audit_ctx

logger = logging.getLogger(__name__)

STREAM_KEY    = "events:review.created"
GROUP_NAME    = "wallet-service"
CONSUMER_NAME = "review-credit-worker-1"
BLOCK_MS      = 0       # non-blocking — use asyncio.sleep for backoff instead
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


async def _credit_points(review_id: str, receiver_id: str, raw_points: int, ip_address: str | None = None) -> None:
    """
    Credit raw_points to the receiver's wallet.
    Idempotent — skips if a transaction for this review_id already exists.
    """

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

    # ── Write transaction + update wallet with audit context ──────────────────
    # Prisma doesn't expose raw transactions via the Python client's batch API
    # in the same way — we use sequential writes with the idempotency guard
    # above as our safety net.
    # receiver_id is used as performed_by — they are the beneficiary of the credit
    # and the closest actor we have in a consumer context (no HTTP request).

    # Snapshot wallet state BEFORE credit — shown as "Before the change" in audit UI
    wallet_before = {
        "available_points":    wallet.available_points,
        "total_earned_points": wallet.total_earned_points,
    }

    # ── Fetch reviewer details for description ────────────────────────────────
    review = await db.reviews.find_unique(
        where={"review_id": review_id},
        include={"employees_reviews_reviewer_idToemployees": True}
    )
    
    reviewer_name = "System"
    if review and review.employees_reviews_reviewer_idToemployees:
        reviewer_name = review.employees_reviews_reviewer_idToemployees.username

    new_txn = None
    async with audit_ctx(
        user_id    = receiver_id,
        request    = None,
        ip_address = ip_address,   # forwarded from Recognition service via stream payload
        table_name = "transactions",
        record_id  = lambda: str(new_txn.transaction_id) if new_txn else "",
        operation  = "CREDIT",
        old_values = wallet_before,
        new_values = lambda: {
            "available_points":    wallet.available_points    + raw_points,
            "total_earned_points": wallet.total_earned_points + raw_points,
            "points_credited":     raw_points,
            "review_id":           review_id,
            "reference":           review_id,
        },
    ):
        new_txn = await db.transactions.create(data={
            "wallet_id":           wallet.wallet_id,
            "amount":              raw_points,
            "transaction_type_id": credit_type.type_id,
            "status_id":           status.status_id,
            "reference_number":    review_id,
            "description":         f"Points credited from review by {reviewer_name}",
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

    # ── Notify receiver — triggers manager CC in the email worker ─────────────
    try:
        from src.notifications.service import NotificationService
        from src.notifications.schemas import NotificationType
        from src.notifications.redis_client import get_redis
        try:
            r = get_redis()
        except RuntimeError:
            r = None
        notif_svc = NotificationService(db, redis=r)
        notif = await notif_svc.create_notification(
            employee_id=receiver_id,
            title="A Performance Review Has Been Submitted",
            message=(
                "A new performance review has been submitted and recorded against "
                "your employee profile on the Aabhar platform."
            ),
            type=NotificationType.REVIEW,
        )
        print(
            f"REVIEW notification created: {notif['notification_id']} "
            f"redis={'SET' if r is not None else 'NONE'}",
            flush=True,
        )
        # If Redis is available, also directly enqueue so the worker picks it up
        # immediately without waiting for recovery
        if r is not None:
            from src.notifications.cache import enqueue_notification
            await enqueue_notification(r, str(notif["notification_id"]))
            print(f"REVIEW notification enqueued: {notif['notification_id']}", flush=True)
    except Exception as _notif_exc:
        logger.warning(
            "REVIEW notification failed for receiver %s (review %s) — "
            "points were still credited: %s",
            receiver_id, review_id, _notif_exc,
            exc_info=True,
        )
        print(
            f"REVIEW notification ERROR receiver={receiver_id} review={review_id}: {_notif_exc}",
            flush=True,
        )


async def review_created_consumer_loop(shutdown_event: asyncio.Event) -> None:
    """
    Long-running coroutine — start as asyncio.Task in Wallet service lifespan.
    """
    print("review.created consumer: loop entered", flush=True)
    from src.notifications.redis_client import get_redis
    try:
        r = get_redis()
    except RuntimeError:
        logger.warning("Redis not available — review.created consumer disabled")
        print("review.created consumer: Redis unavailable — exiting", flush=True)
        return

    print("review.created consumer: Redis OK, ensuring group...", flush=True)
    await _ensure_group(r)
    await _recover_pending(r)
    logger.info("review.created consumer started")
    print("review.created consumer started ✅", flush=True)

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
                await asyncio.sleep(0.5)
                continue

            for _stream, messages in results:
                for msg_id, fields in messages:
                    await _handle_message(r, msg_id, fields)
            await asyncio.sleep(0)

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
    ip_address  = fields.get("ip_address") or None   # forwarded from Recognition service publisher
    try:
        raw_points = int(fields.get("raw_points", "0"))
    except ValueError:
        raw_points = 0

    if not review_id or not receiver_id:
        logger.warning("review.created msg %s missing fields — ACKing", msg_id)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        return

    try:
        await _credit_points(review_id, receiver_id, raw_points, ip_address)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except RuntimeError as exc:
        err = str(exc)
        # Unrecoverable: missing transaction type or status will never self-heal.
        # Wallet-not-found is retryable (wallet may still be provisioning).
        if "not found" in err.lower() and "wallet" not in err.lower():
            logger.error(
                "Dead-letter: unrecoverable error crediting review %s to employee %s: %s — ACKing",
                review_id, receiver_id, exc,
            )
            await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        else:
            # Transient or wallet-not-yet-ready — leave pending for retry
            logger.error(
                "Failed to credit review %s to employee %s: %s",
                review_id, receiver_id, exc,
            )
    except Exception as exc:
        logger.error(
            "Failed to credit review %s to employee %s: %s",
            review_id, receiver_id, exc,
        )