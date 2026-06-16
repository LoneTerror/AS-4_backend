"""
src/wallet/reward_consumer.py
──────────────────────────────
Redis Stream consumer — listens on 'events:reward.redeemed'
and deducts points from the wallet's available_points.

Previously the Rewards service wrote directly to the wallets table.
Now it publishes this event and the Wallet service handles the deduction.

Idempotency: checks for an existing DEBIT transaction with
reference_number = history_id before writing.

Consumer group : wallet-service
Consumer name  : reward-debit-worker-1
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

# Imports at module level — lazy imports inside async functions can fail
# silently on first call (import error caught by bare except) causing messages
# to be silently dropped during live operation and only processed on restart
# once the import cache is warm.
from src.prisma.client import db
from src.common.audit import audit_ctx

logger = logging.getLogger(__name__)

STREAM_KEY    = "events:reward.redeemed"
GROUP_NAME    = "wallet-service"
CONSUMER_NAME = "reward-debit-worker-1"
BLOCK_MS      = 0       # non-blocking — use asyncio.sleep for backoff instead
BATCH_SIZE    = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_group(r) -> None:
    try:
        await r.xgroup_create(STREAM_KEY, GROUP_NAME, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def _deduct_points(
    history_id: str, wallet_id: str, points: int, redeemed_by: str, ip_address: str | None = None
) -> None:
    """Deduct points from wallet. Idempotent via reference_number check."""

    existing = await db.transactions.find_first(
        where={"reference_number": f"redemption:{history_id}"}
    )
    if existing:
        logger.debug("Deduction for redemption %s already recorded — skipping", history_id)
        return

    wallet = await db.wallets.find_first(where={"wallet_id": wallet_id})
    if not wallet:
        raise RuntimeError(f"Wallet {wallet_id} not found")

    if wallet.available_points < points:
        logger.warning(
            "Insufficient points for wallet %s (has %d, needs %d) — redemption %s",
            wallet_id, wallet.available_points, points, history_id,
        )
        # Still write the transaction to record the attempt and ACK.
        # The Rewards service validates balance before issuing the event,
        # so this path should be rare in practice.
        points = min(points, wallet.available_points)

    debit_type = await db.transaction_types.find_first(
        where={"is_credit": False, "type_code": "REWARD_REDEMPTION"}
    ) or await db.transaction_types.find_first(where={"is_credit": False})

    status = await db.status_master.find_first(
        where={"status_code": "SUCCESS", "entity_type": "TRANSACTION"}
    ) or await db.status_master.find_first(where={"status_code": "SUCCESS"})

    if not debit_type or not status:
        raise RuntimeError("Missing debit transaction_type or SUCCESS status in DB")

    # Snapshot wallet state BEFORE deduction — shown as "Before the change" in audit UI
    wallet_before = {
        "available_points": wallet.available_points,
        "redeemed_points":  wallet.redeemed_points,
    }

    new_txn = None
    async with audit_ctx(
        user_id    = redeemed_by,
        request    = None,
        ip_address = ip_address,   # forwarded from Rewards service via stream payload
        table_name = "transactions",
        record_id  = lambda: str(new_txn.transaction_id),
        operation  = "REDEEM",
        old_values = wallet_before,
        new_values = lambda: {
            "available_points": wallet.available_points - points,
            "redeemed_points":  wallet.redeemed_points  + points,
            "points_deducted":  points,
            "history_id":       history_id,
            "reference":        f"redemption:{history_id}",
        },
    ):
        new_txn = await db.transactions.create(data={
            "wallet_id":           wallet_id,
            "amount":              points,
            "transaction_type_id": debit_type.type_id,
            "status_id":           status.status_id,
            "reference_number":    f"redemption:{history_id}",
            "description":         f"Points deducted for reward redemption {history_id}",
            "transaction_at":      _now(),
            "created_by":          redeemed_by,
            "updated_by":          redeemed_by,
            "updated_at":          _now(),
        })

        await db.wallets.update(
            where={"wallet_id": wallet_id},
            data={
                "available_points": {"decrement": points},
                "redeemed_points":  {"increment": points},
                "updated_by":       redeemed_by,
                "updated_at":       _now(),
            },
        )

    # ── Invalidate wallet cache so the next read reflects the deduction ────
    # wallet.employee_id is already in scope from the find_first above —
    # no extra DB query needed. Key must match _wallet_key() in service.py.
    try:
        from src.common.cache import cache_delete
        await cache_delete(f"wallets:employee:{wallet.employee_id}")
        logger.debug(
            "Cache busted for employee %s after redemption %s",
            wallet.employee_id, history_id,
        )
    except Exception as exc:
        logger.warning(
            "Cache invalidation failed after deduction %s: %s", history_id, exc
        )

    logger.info(
        "Deducted %d points from wallet %s for redemption %s",
        points, wallet_id, history_id,
    )
    print(f"reward.redeemed: deducted {points} pts wallet={wallet_id} redemption={history_id} ✅", flush=True)

    # ── Notify employee — triggers manager CC in the email worker ─────────────
    try:
        from src.notifications.service import NotificationService
        from src.notifications.schemas import NotificationType
        from src.notifications.redis_client import get_redis
        try:
            r = get_redis()
        except RuntimeError:
            r = None
        await NotificationService(db, redis=r).create_notification(
            employee_id=wallet.employee_id,
            title=f"Reward Redeemed — {points} points deducted",
            message=(
                f"{points} points have been deducted from your wallet "
                f"for reward redemption (Ref: {history_id})."
            ),
            type=NotificationType.REWARD,
        )
    except Exception:
        logger.warning(
            "REWARD notification failed for wallet %s (redemption %s) — "
            "points were still deducted",
            wallet_id, history_id,
        )


async def reward_redeemed_consumer_loop(shutdown_event: asyncio.Event) -> None:
    from src.notifications.redis_client import get_redis
    try:
        r = get_redis()
    except RuntimeError:
        logger.warning("Redis unavailable — reward.redeemed consumer disabled")
        return

    await _ensure_group(r)
    await _recover_pending(r)
    logger.info("reward.redeemed consumer started")
    print("reward.redeemed consumer started ✅", flush=True)

    while not shutdown_event.is_set():
        try:
            results = await r.xreadgroup(
                groupname=GROUP_NAME, consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"}, count=BATCH_SIZE, block=BLOCK_MS,
            )
            if not results:
                await asyncio.sleep(0.5)
                continue
            for _stream, messages in results:
                for msg_id, fields in messages:
                    print(f"reward.redeemed: received msg {msg_id}", flush=True)
                    logger.info("reward.redeemed: received msg %s", msg_id)
                    await _handle_message(r, msg_id, fields)
            # Yield after processing a batch so the event loop isn't starved
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("reward.redeemed consumer error: %s", exc)
            if "NOGROUP" in str(exc):
                try:
                    await _ensure_group(r)
                except Exception as eg_exc:
                    logger.error("reward.redeemed _ensure_group recovery failed: %s", eg_exc)
            await asyncio.sleep(2)

    logger.info("reward.redeemed consumer stopped")


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
        logger.warning("reward.redeemed recovery failed: %s", exc)


async def _handle_message(r, msg_id: str, fields: dict) -> None:
    history_id  = fields.get("history_id", "")
    wallet_id   = fields.get("wallet_id", "")
    redeemed_by = fields.get("redeemed_by", "system")
    ip_address  = fields.get("ip_address") or None   # forwarded from Rewards service publisher
    try:
        points = int(fields.get("points", "0"))
    except ValueError:
        points = 0

    if not history_id or not wallet_id:
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        return

    try:
        await _deduct_points(history_id, wallet_id, points, redeemed_by, ip_address)
        await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
    except RuntimeError as exc:
        err = str(exc)
        # Unrecoverable errors — wallet/status missing will never self-heal.
        # ACK to stop the infinite retry loop and log as a dead-letter event.
        if "not found" in err.lower() or "missing" in err.lower():
            logger.error(
                "Dead-letter: unrecoverable error for redemption %s (wallet=%s): %s — ACKing to prevent infinite retry",
                history_id, wallet_id, exc,
            )
            await r.xack(STREAM_KEY, GROUP_NAME, msg_id)
        else:
            # Transient error (e.g. DB timeout) — leave pending for retry
            logger.error("Failed to deduct points for redemption %s: %s", history_id, exc)
    except Exception as exc:
        logger.error("Failed to deduct points for redemption %s: %s", history_id, exc)