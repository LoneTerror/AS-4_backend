# src/webhooks/service.py
"""
Webhook service — handles HRIS push events.

Bugs fixed vs original router.py:
  1. WEBHOOK_SECRET env var typo fixed  (was "AGLORITHM")
  2. Signature verification re-enabled
  3. publish("events:employee.created") added after employee create
     so Wallet Service creates the wallet automatically
  4. Idempotency — event_id deduped in Redis (TTL 24h)
  5. password_hash left intentionally empty + comment explaining SSO flow
  6. entity_type confirmed as "GENERAL" (matches seed.py)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone

from fastapi import HTTPException, Request, status
from prisma import Prisma

from src.common.event_publisher import publish
from src.notifications.cache import (
    dept_key, desig_key, status_key,
    get_cached_lookup, set_cached_lookup,
    invalidate_employee,
)
from src.webhooks.schemas import (
    HrisEmployeeCreatedPayload,
    HrisEmployeeUpdatedPayload,
    HrisEmployeeStatusPayload,
    HrisWebhookEvent,
)

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
# FIX 1: was os.environ.get("AGLORITHM", "") — typo meant secret was always ""
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

_IDEMPOTENCY_TTL = 86_400  # 24 hours


# ── Signature verification ────────────────────────────────────────────────────

def verify_signature(body: bytes, x_webhook_signature: str) -> None:
    """
    Raises HTTP 401 if the HMAC-SHA256 signature does not match.
    FIX 2: was commented out in original router — now called from router.
    """
    if not WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set — skipping signature check (dev only)")
        return

    expected = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, x_webhook_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )


# ── Idempotency ───────────────────────────────────────────────────────────────

async def _is_duplicate(r, event_id: str) -> bool:
    """
    FIX 4: Returns True if this event_id was already processed.
    Stores the key in Redis for 24h using SET NX.
    """
    if r is None or not event_id:
        return False
    key = f"webhook:idempotency:{event_id}"
    result = await r.set(key, "1", nx=True, ex=_IDEMPOTENCY_TTL)
    return result is None  # None means key already existed


# ── Main dispatcher ───────────────────────────────────────────────────────────

async def handle_hris_event(
    request: Request,
    event:   HrisWebhookEvent,
    db:      Prisma,
) -> dict:
    r = getattr(request.app.state, "redis", None)

    # FIX 2: Signature verification — read raw body for HMAC check
    body      = await request.body()
    signature = request.headers.get("x-webhook-signature", "")
    verify_signature(body, signature)

    logger.info("HRIS webhook received: event=%s id=%s", event.event, event.event_id)

    # FIX 4: Idempotency check
    if event.event_id and await _is_duplicate(r, event.event_id):
        logger.info("HRIS webhook: duplicate event_id=%s — skipping", event.event_id)
        return {"received": True, "event": event.event, "skipped": True}

    if event.event == "employee.created":
        await _handle_employee_created(db, r, HrisEmployeeCreatedPayload(**event.data))

    elif event.event == "employee.updated":
        await _handle_employee_updated(db, r, HrisEmployeeUpdatedPayload(**event.data))

    elif event.event == "employee.status_changed":
        await _handle_status_changed(db, r, HrisEmployeeStatusPayload(**event.data))

    else:
        logger.warning("HRIS webhook: unknown event type %r — ignoring", event.event)

    return {"received": True, "event": event.event}


# ── Shared lookup helpers (with cache) ───────────────────────────────────────

async def _get_dept(db: Prisma, r, code: str):
    if r:
        cached = await get_cached_lookup(r, dept_key(code))
        if cached:
            return type("Dept", (), cached)()
    dept = await db.departments.find_first(where={"department_code": code})
    if dept and r:
        await set_cached_lookup(r, dept_key(code), {
            "department_id":   str(dept.department_id),
            "department_code": dept.department_code,
        })
    return dept


async def _get_desig(db: Prisma, r, code: str):
    if r:
        cached = await get_cached_lookup(r, desig_key(code))
        if cached:
            return type("Desig", (), cached)()
    desig = await db.designations.find_first(where={"designation_code": code})
    if desig and r:
        await set_cached_lookup(r, desig_key(code), {
            "designation_id":   str(desig.designation_id),
            "designation_code": desig.designation_code,
        })
    return desig


async def _get_status(db: Prisma, r, code: str):
    if r:
        cached = await get_cached_lookup(r, status_key(code))
        if cached:
            return type("Status", (), cached)()
    # entity_type="GENERAL" confirmed from seed.py
    row = await db.status_master.find_first(
        where={"status_code": code, "entity_type": "GENERAL"}
    )
    if row and r:
        await set_cached_lookup(r, status_key(code), {
            "status_id":   str(row.status_id),
            "status_code": row.status_code,
        })
    return row


# ── Event handlers ────────────────────────────────────────────────────────────

async def _handle_employee_created(
    db:      Prisma,
    r,
    payload: HrisEmployeeCreatedPayload,
) -> None:
    existing = await db.employees.find_first(where={"email": payload.email})
    if existing:
        logger.info("HRIS webhook: employee %s already exists — skipping", payload.email)
        return

    dept = await _get_dept(db, r, payload.department_code)
    if not dept:
        raise HTTPException(status_code=400, detail=f"Unknown department_code: {payload.department_code}")

    desig = await _get_desig(db, r, payload.designation_code)
    if not desig:
        raise HTTPException(status_code=400, detail=f"Unknown designation_code: {payload.designation_code}")

    status_row = await _get_status(db, r, "ACTIVE")
    if not status_row:
        raise HTTPException(status_code=500, detail="ACTIVE status not found in status_master.")

    manager_id: str | None = None
    if payload.manager_email:
        mgr = await db.employees.find_first(where={"email": payload.manager_email})
        if mgr:
            manager_id = str(mgr.employee_id)
        else:
            logger.warning(
                "HRIS webhook: manager %s not found — manager_id will be null",
                payload.manager_email,
            )

    now = datetime.now(tz=timezone.utc)
    new_emp = await db.employees.create(
        data={
            "username":        payload.username,
            "email":           payload.email,
            "department_id":   str(dept.department_id),
            "designation_id":  str(desig.designation_id),
            "status_id":       str(status_row.status_id),
            "date_of_joining": datetime.fromisoformat(payload.date_of_joining),
            "date_of_birth":   (
                datetime.fromisoformat(payload.date_of_birth)
                if payload.date_of_birth else None
            ),
            "manager_id":      manager_id,
            # FIX 5: Empty password_hash is intentional for HRIS-provisioned accounts.
            # These employees authenticate via SSO / password-reset flow.
            # They cannot log in with a password until they complete the reset flow.
            "password_hash":   "",
            "created_at":      now,
            "updated_at":      now,
        }
    )

    # FIX 3: Publish event so Wallet Service creates the wallet automatically.
    # Original code was missing this entirely — HRIS employees had no wallet.
    await publish("events:employee.created", {
        "employee_id": str(new_emp.employee_id),
        "created_by":  "hris_webhook",
    })

    logger.info("HRIS webhook: employee created and event published — %s", payload.email)


async def _handle_employee_updated(
    db:      Prisma,
    r,
    payload: HrisEmployeeUpdatedPayload,
) -> None:
    emp = await db.employees.find_first(where={"email": payload.email})
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee not found: {payload.email}")

    patch: dict = {"updated_at": datetime.now(tz=timezone.utc)}

    if payload.department_code:
        dept = await _get_dept(db, r, payload.department_code)
        if not dept:
            raise HTTPException(status_code=400, detail=f"Unknown department_code: {payload.department_code}")
        patch["department_id"] = str(dept.department_id)

    if payload.designation_code:
        desig = await _get_desig(db, r, payload.designation_code)
        if not desig:
            raise HTTPException(status_code=400, detail=f"Unknown designation_code: {payload.designation_code}")
        patch["designation_id"] = str(desig.designation_id)

    if payload.manager_email:
        mgr = await db.employees.find_first(where={"email": payload.manager_email})
        if mgr:
            patch["manager_id"] = str(mgr.employee_id)

    if payload.date_of_birth:
        patch["date_of_birth"] = datetime.fromisoformat(payload.date_of_birth)

    await db.employees.update(
        where={"employee_id": str(emp.employee_id)},
        data=patch,
    )

    if r:
        await invalidate_employee(r, str(emp.employee_id))

    logger.info("HRIS webhook: employee updated — %s", payload.email)


async def _handle_status_changed(
    db:      Prisma,
    r,
    payload: HrisEmployeeStatusPayload,
) -> None:
    emp = await db.employees.find_first(where={"email": payload.email})
    if not emp:
        raise HTTPException(status_code=404, detail=f"Employee not found: {payload.email}")

    status_row = await _get_status(db, r, payload.status_code)
    if not status_row:
        raise HTTPException(status_code=400, detail=f"Unknown status_code: {payload.status_code}")

    await db.employees.update(
        where={"employee_id": str(emp.employee_id)},
        data={
            "status_id":  str(status_row.status_id),
            "updated_at": datetime.now(tz=timezone.utc),
        },
    )

    if r:
        await invalidate_employee(r, str(emp.employee_id))

    logger.info(
        "HRIS webhook: status changed — %s -> %s",
        payload.email, payload.status_code,
    )
