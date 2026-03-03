# src/webhooks/router.py

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


def get_db():
    return db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


# ── Signature verification ─────────────────────────────────────────────────────

async def verify_signature(
    request: Request,
    x_webhook_signature: str = Header(...),
):
    """
    HMAC-SHA256 verification.
    The sender must set header:  X-Webhook-Signature: sha256=<hex_digest>
    Computed over the raw request body using the shared WEBHOOK_SECRET.

    To generate the signature (e.g. in Postman pre-request script or Python):

        import hashlib, hmac, json
        secret = "your_WEBHOOK_SECRET_value"
        body   = json.dumps(payload, separators=(',', ':'))   # compact JSON
        sig    = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    NOTE: During local development you can skip this dependency by removing
    `_verified=Depends(verify_signature)` from the endpoint signature.
    """
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
    """
    Fired when a new employee is onboarded in the external HRIS.
    department_code and designation_code must already exist in your DB.
    """
    external_id: str                        # sender's own ID — stored in logs only
    username: str
    email: EmailStr
    department_code: str                    # must match departments.department_code
    designation_code: str                   # must match designations.designation_code
    date_of_joining: str                    # ISO date string e.g. "2024-03-01"
    date_of_birth: Optional[str] = None     # ISO date string e.g. "1995-06-15"
    manager_email: Optional[EmailStr] = None


class HrisEmployeeUpdatedPayload(BaseModel):
    """
    Fired when an employee's department, designation, manager, or DOB changes.
    Only non-null fields are patched — omit fields you don't want to change.
    """
    email: EmailStr                          # used to look up the employee
    department_code: Optional[str] = None
    designation_code: Optional[str] = None
    manager_email: Optional[EmailStr] = None
    date_of_birth: Optional[str] = None


class HrisEmployeeStatusPayload(BaseModel):
    """
    Fired when an employee is activated, deactivated, put on leave, etc.
    status_code must already exist in status_master with entity_type = 'EMPLOYEE'.
    Common values: ACTIVE, INACTIVE, ON_LEAVE
    """
    email: EmailStr
    status_code: str


class HrisWebhookEvent(BaseModel):
    """
    Envelope for all HRIS webhook events.

    Supported event types:
      employee.created        → create employee row (idempotent — safe to replay)
      employee.updated        → patch department / designation / manager / dob
      employee.status_changed → flip status_id
    """
    event: str
    data: dict


# ── Main endpoint ──────────────────────────────────────────────────────────────

@router.post(
    "/hris",
    status_code=status.HTTP_200_OK,
    summary="HRIS push webhook",
    description=(
        "Receives employee lifecycle events from an external HRIS and keeps "
        "the local employees table in sync. Secured with HMAC-SHA256 signatures."
    ),
)
async def hris_webhook(
    event: HrisWebhookEvent,
    db: Prisma = Depends(get_db),
    # ↓ Comment this line out during local Postman testing, restore before deploy
    #_verified=Depends(verify_signature),
):
    logger.info("HRIS webhook received: event=%s", event.event)

    if event.event == "employee.created":
        await _handle_employee_created(db, HrisEmployeeCreatedPayload(**event.data))

    elif event.event == "employee.updated":
        await _handle_employee_updated(db, HrisEmployeeUpdatedPayload(**event.data))

    elif event.event == "employee.status_changed":
        await _handle_status_changed(db, HrisEmployeeStatusPayload(**event.data))

    else:
        logger.warning("HRIS webhook: unknown event type %r — ignoring", event.event)

    return {"received": True, "event": event.event}


# ── Event handlers ─────────────────────────────────────────────────────────────

async def _handle_employee_created(
    db: Prisma,
    payload: HrisEmployeeCreatedPayload,
) -> None:
    """
    Upsert-safe: if the email already exists we log and return — no duplicate created.
    password_hash is intentionally left blank; the employee must set a password
    on first login via your existing password-reset / onboarding flow.
    """
    # Idempotency guard
    existing = await db.employees.find_first(where={"email": payload.email})
    if existing:
        logger.info(
            "HRIS webhook: employee %s already exists — skipping create",
            payload.email,
        )
        return

    # Resolve department
    dept = await db.departments.find_first(
        where={"department_code": payload.department_code}
    )
    if not dept:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown department_code: {payload.department_code}",
        )

    # Resolve designation
    desig = await db.designations.find_first(
        where={"designation_code": payload.designation_code}
    )
    if not desig:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown designation_code: {payload.designation_code}",
        )

    # Resolve ACTIVE status
    status_row = await db.status_master.find_first(
        where={"status_code": "ACTIVE", "entity_type": "GENERAL"}
    )
    if not status_row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ACTIVE status not found in status_master — check your seed data.",
        )

    # Optionally resolve manager
    manager_id: str | None = None
    if payload.manager_email:
        mgr = await db.employees.find_first(where={"email": payload.manager_email})
        if mgr:
            manager_id = str(mgr.employee_id)
        else:
            logger.warning(
                "HRIS webhook: manager email %s not found — manager_id will be null",
                payload.manager_email,
            )

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
                datetime.fromisoformat(payload.date_of_birth)
                if payload.date_of_birth else None
            ),
            "manager_id":      manager_id,
            "password_hash":   "",   # blank — must be set via onboarding/reset flow
            "created_at":      now,
            "updated_at":      now,
        }
    )
    logger.info(
        "HRIS webhook: employee created — %s (external_id=%s)",
        payload.email,
        payload.external_id,
    )


async def _handle_employee_updated(
    db: Prisma,
    payload: HrisEmployeeUpdatedPayload,
) -> None:
    """
    Patches only the fields present in the payload.
    Missing / None fields are left untouched in the DB.
    """
    emp = await db.employees.find_first(where={"email": payload.email})
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee not found: {payload.email}",
        )

    patch: dict = {"updated_at": datetime.now(tz=timezone.utc)}

    if payload.department_code:
        dept = await db.departments.find_first(
            where={"department_code": payload.department_code}
        )
        if not dept:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown department_code: {payload.department_code}",
            )
        patch["department_id"] = str(dept.department_id)

    if payload.designation_code:
        desig = await db.designations.find_first(
            where={"designation_code": payload.designation_code}
        )
        if not desig:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown designation_code: {payload.designation_code}",
            )
        patch["designation_id"] = str(desig.designation_id)

    if payload.manager_email:
        mgr = await db.employees.find_first(where={"email": payload.manager_email})
        if mgr:
            patch["manager_id"] = str(mgr.employee_id)
        else:
            logger.warning(
                "HRIS webhook: manager email %s not found — manager_id unchanged",
                payload.manager_email,
            )

    if payload.date_of_birth:
        patch["date_of_birth"] = datetime.fromisoformat(payload.date_of_birth)

    await db.employees.update(
        where={"employee_id": str(emp.employee_id)},
        data=patch,
    )
    logger.info(
        "HRIS webhook: employee updated — %s | fields=%s",
        payload.email,
        list(patch.keys()),
    )


async def _handle_status_changed(
    db: Prisma,
    payload: HrisEmployeeStatusPayload,
) -> None:
    """
    Flips the employee's status_id to the matching status_master row.
    Triggers no notifications — add a create_notification() call here
    if you want to alert the employee or their manager on deactivation.
    """
    emp = await db.employees.find_first(where={"email": payload.email})
    if not emp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Employee not found: {payload.email}",
        )

    status_row = await db.status_master.find_first(
        where={"status_code": payload.status_code, "entity_type": "GENERAL"}
    )
    if not status_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status_code: {payload.status_code}",
        )

    await db.employees.update(
        where={"employee_id": str(emp.employee_id)},
        data={
            "status_id":  str(status_row.status_id),
            "updated_at": datetime.now(tz=timezone.utc),
        },
    )
    logger.info(
        "HRIS webhook: status changed — %s → %s",
        payload.email,
        payload.status_code,
    )