# src/webhooks/router.py
"""
Webhooks router — unchanged except:
  - imports cache.invalidate_employee so HRIS updates bust the Redis cache
  - passes redis from app.state into handlers
"""

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from prisma import Prisma
from pydantic import BaseModel, EmailStr

from src.prisma.client import db
from src.notifications.cache import (
    invalidate_employee,
    dept_key, desig_key, status_key,
    set_cached_lookup, get_cached_lookup,
)


def get_db():
    return db

def get_redis(request: Request):
    return getattr(request.app.state, "redis", None)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])

WEBHOOK_SECRET = os.environ.get("AGLORITHM", "")


# ── Signature verification ─────────────────────────────────────────────────────

async def verify_signature(
    request: Request,
    x_webhook_signature: str = Header(...),
):
    body = await request.body()
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


# ── Payload schemas ────────────────────────────────────────────────────────────

class HrisEmployeeCreatedPayload(BaseModel):
    external_id: str
    username: str
    email: EmailStr
    department_code: str
    designation_code: str
    date_of_joining: str
    date_of_birth: Optional[str] = None
    manager_email: Optional[EmailStr] = None


class HrisEmployeeUpdatedPayload(BaseModel):
    email: EmailStr
    department_code: Optional[str] = None
    designation_code: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    date_of_birth: Optional[str] = None


class HrisEmployeeStatusPayload(BaseModel):
    email: EmailStr
    status_code: str


class HrisWebhookEvent(BaseModel):
    event: str
    data: dict


# ── Main endpoint ──────────────────────────────────────────────────────────────

@router.post(
    "/hris",
    status_code=status.HTTP_200_OK,
    summary="HRIS push webhook",
)
async def hris_webhook(
    request: Request,
    event: HrisWebhookEvent,
    db: Prisma = Depends(get_db),
    # _verified=Depends(verify_signature),
):
    r = get_redis(request)
    logger.info("HRIS webhook received: event=%s", event.event)

    if event.event == "employee.created":
        await _handle_employee_created(db, r, HrisEmployeeCreatedPayload(**event.data))

    elif event.event == "employee.updated":
        await _handle_employee_updated(db, r, HrisEmployeeUpdatedPayload(**event.data))

    elif event.event == "employee.status_changed":
        await _handle_status_changed(db, r, HrisEmployeeStatusPayload(**event.data))

    else:
        logger.warning("HRIS webhook: unknown event type %r — ignoring", event.event)

    return {"received": True, "event": event.event}


# ── Shared lookup helpers (with cache) ────────────────────────────────────────

async def _get_dept(db: Prisma, r, code: str):
    if r:
        cached = await get_cached_lookup(r, dept_key(code))
        if cached:
            return type("Dept", (), cached)()  # lightweight object with dict attrs
    dept = await db.departments.find_first(where={"department_code": code})
    if dept and r:
        await set_cached_lookup(r, dept_key(code), {
            "department_id": str(dept.department_id),
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
            "designation_id": str(desig.designation_id),
            "designation_code": desig.designation_code,
        })
    return desig


async def _get_status(db: Prisma, r, code: str):
    if r:
        cached = await get_cached_lookup(r, status_key(code))
        if cached:
            return type("Status", (), cached)()
    row = await db.status_master.find_first(
        where={"status_code": code, "entity_type": "GENERAL"}
    )
    if row and r:
        await set_cached_lookup(r, status_key(code), {
            "status_id": str(row.status_id),
            "status_code": row.status_code,
        })
    return row


# ── Event handlers ─────────────────────────────────────────────────────────────

async def _handle_employee_created(db: Prisma, r, payload: HrisEmployeeCreatedPayload) -> None:
    existing = await db.employees.find_first(where={"email": payload.email})
    if existing:
        logger.info("HRIS webhook: employee %s already exists — skipping create", payload.email)
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
            logger.warning("HRIS webhook: manager %s not found — manager_id will be null", payload.manager_email)

    now = datetime.now(tz=timezone.utc)
    await db.employees.create(
        data={
            "username":        payload.username,
            "email":           payload.email,
            "department_id":   str(dept.department_id),
            "designation_id":  str(desig.designation_id),
            "status_id":       str(status_row.status_id),
            "date_of_joining": datetime.fromisoformat(payload.date_of_joining),
            "date_of_birth":   (
                datetime.fromisoformat(payload.date_of_birth) if payload.date_of_birth else None
            ),
            "manager_id":      manager_id,
            "password_hash":   "",
            "created_at":      now,
            "updated_at":      now,
        }
    )
    logger.info("HRIS webhook: employee created — %s", payload.email)


async def _handle_employee_updated(db: Prisma, r, payload: HrisEmployeeUpdatedPayload) -> None:
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

    await db.employees.update(where={"employee_id": str(emp.employee_id)}, data=patch)

    # Bust the employee cache so the worker picks up fresh data
    if r:
        await invalidate_employee(r, str(emp.employee_id))

    logger.info("HRIS webhook: employee updated — %s", payload.email)


async def _handle_status_changed(db: Prisma, r, payload: HrisEmployeeStatusPayload) -> None:
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

    # Bust employee cache — status change affects active-employee lists
    if r:
        await invalidate_employee(r, str(emp.employee_id))

    logger.info("HRIS webhook: status changed — %s → %s", payload.email, payload.status_code)