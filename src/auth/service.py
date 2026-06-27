"""
src/auth/service.py
───────────────────
Auth service — owns: employees (auth columns), refresh_tokens.

DECOUPLING CHANGE
──────────────────
Wallet creation removed from create_employee().
After persisting the employee row, publishes 'employee.created'
to a Redis Stream. The Wallet service consumes and provisions
the wallet asynchronously.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, cast
import prisma.types
from uuid import uuid4

from fastapi import HTTPException, Request, status

from src.common.audit import audit, audit_ctx
from src.common.event_publisher import publish
from src.prisma.client import db
from src.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    create_reset_token,
    decode_reset_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
    verify_refresh_token,
)

try:
    from src.core.email_utils import send_password_reset_confirmation, send_password_reset_email
    _email_available = True
except Exception as _err:
    _email_available = False
    def send_password_reset_email(*a, **kw) -> bool: return False
    def send_password_reset_confirmation(*a, **kw) -> bool: return False

logger = logging.getLogger(__name__)

_TOKEN_SEP = "||"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_login_response(user, access_token: str, refresh_token_raw: str) -> dict:
    return {
        "access_token":  access_token,
        "refresh_token": refresh_token_raw,
        "token_type":    "Bearer",
        "expires_in":    ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "employee": {
            "employee_id":    user.employee_id,
            "username":       user.username,
            "email":          user.email,
            "designation_id": user.designation_id,
            "department_id":  user.department_id,
            "must_change_password": user.must_change_password,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Token validation  (no audit — read-only, called on every request)
# ─────────────────────────────────────────────────────────────────────────────

async def validate_token(token: str) -> dict:
    payload = decode_token(token)
    if not payload:
        return {"valid": False, "error": "Invalid or expired token"}
    return {
        "valid":         True,
        "user_id":       payload.get("sub"),
        "email":         payload.get("email"),
        "roles":         payload.get("roles", []),
        "department_id": payload.get("department_id"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Login
# Audits: successful login (INSERT on refresh_tokens triggers DB audit).
# Failed login audited explicitly — no DB row exists to trigger on.
# ─────────────────────────────────────────────────────────────────────────────

async def authenticate_user(
    username: str,
    password: str,
    request: Optional[Request] = None,
) -> dict:
    username = username.strip().lower()

    user = await db.employees.find_first(
        where={
            "OR": [
                {"username": {"equals": username, "mode": "insensitive"}},
                {"email":    {"equals": username, "mode": "insensitive"}},
            ]
        },
        include={
            "employee_roles_employee_roles_employee_idToemployees": {
                "where":   {"is_active": True},
                "include": {"roles": True},
            }
        },
    )

    # ── Failed login — audit explicitly (no DB row to trigger on) ─────────────
    if not user or not verify_password(password, user.password_hash):
        # Use sentinel UUID as performed_by — no authenticated user exists yet
        await audit(
            table_name   = "employees",
            record_id    = str(user.employee_id) if user else "00000000-0000-0000-0000-000000000000",
            operation    = "LOGIN_FAILED",
            performed_by = str(user.employee_id) if user else "00000000-0000-0000-0000-000000000000",
            new_values   = {"username": username, "reason": "invalid_credentials"},
            request      = request,
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    roles: list[str] = []
    try:
        for er in (user.employee_roles_employee_roles_employee_idToemployees or []):
            if er.roles and hasattr(er.roles, "role_code"):
                roles.append(er.roles.role_code)
    except Exception as exc:
        logger.warning("Role extraction failed for %s: %s", user.employee_id, exc)
    if not roles:
        roles = ["EMPLOYEE"]

    access_token  = create_access_token({
        "sub": str(user.employee_id), "email": user.email,
        "roles": roles, "department_id": str(user.department_id),
    })
    token_id      = str(uuid4())
    token_secret  = secrets.token_urlsafe(64)
    client_token  = f"{token_id}{_TOKEN_SEP}{token_secret}"

    # DB trigger fires on the refresh_tokens INSERT — captures LOGIN implicitly.
    # We also write an explicit app-level audit row with richer context.
    token_record = None
    async with audit_ctx(
        user_id    = str(user.employee_id),
        request    = request,
        table_name = "refresh_tokens",
        record_id  = lambda: str(token_record.token_id) if token_record else "UNKNOWN",
        operation  = "LOGIN",
        new_values = lambda: {
            "employee_id": str(user.employee_id),
            "username":    user.username,
            "roles":       roles,
        },
    ):
        token_record = await db.refresh_tokens.create(
            data=cast(prisma.types.refresh_tokensCreateInput, {
            "token_id":    token_id,
            "token_hash":  hash_refresh_token(token_secret),
            "employee_id": str(user.employee_id),
            "expires_at":  _now() + timedelta(days=7),
            "created_at":  _now(),
            "updated_at":  _now(),
        })
    )

    return _build_login_response(user, access_token, client_token)


# ─────────────────────────────────────────────────────────────────────────────
# Refresh token  (no extra audit — DB trigger on refresh_tokens UPDATE covers it)
# ─────────────────────────────────────────────────────────────────────────────

async def refresh_access_token(client_refresh_token: str) -> dict:
    if _TOKEN_SEP not in client_refresh_token:
        raise HTTPException(status_code=401, detail="Invalid token format")

    token_id, token_secret = client_refresh_token.split(_TOKEN_SEP, 1)
    stored = await db.refresh_tokens.find_unique(
        where={"token_id": token_id}, include={"employees": True}
    )
    if not stored:
        raise HTTPException(status_code=401, detail="Token not found")
    if stored.revoked_at or stored.expires_at < _now():
        raise HTTPException(status_code=401, detail="Token expired or revoked")
    if not verify_refresh_token(token_secret, stored.token_hash):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    user  = stored.employees
    if not user:
        raise HTTPException(status_code=401, detail="User record not found for this token")
    
    roles: list[str] = []
    try:
        relations = await db.employee_roles.find_many(
            where={"employee_id": user.employee_id, "is_active": True},
            include={"roles": True},
        )
        roles = [r.roles.role_code for r in relations if r.roles and r.is_active]
    except Exception as exc:
        logger.warning("Refresh role extraction failed: %s", exc)
    if not roles:
        roles = ["EMPLOYEE"]

    new_access = create_access_token({
        "sub": str(user.employee_id), "email": user.email,
        "roles": roles, "department_id": str(user.department_id),
    })
    return _build_login_response(user, new_access, client_refresh_token)


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# DB trigger on refresh_tokens UPDATE fires automatically.
# App-level audit row adds explicit LOGOUT operation for clarity.
# ─────────────────────────────────────────────────────────────────────────────

async def logout_user(
    client_refresh_token: str,
    user_id: str,
    request: Optional[Request] = None,
) -> dict:
    if _TOKEN_SEP not in client_refresh_token:
        return {"message": "Invalid token format, but logged out locally"}

    token_id, token_secret = client_refresh_token.split(_TOKEN_SEP, 1)
    stored = await db.refresh_tokens.find_first(
        where={"token_id": token_id, "employee_id": user_id}
    )

    if stored and verify_refresh_token(token_secret, stored.token_hash):
        async with audit_ctx(
            user_id    = user_id,
            request    = request,
            table_name = "refresh_tokens",
            record_id  = str(stored.token_id),
            operation  = "LOGOUT",
            old_values = {"revoked_at": None},
            new_values = {"revoked_at": _now().isoformat()},
        ):
            await db.refresh_tokens.update(
                where={"token_id": token_id},
                data={"revoked_at": _now(), "updated_at": _now()},
            )

    return {"message": "Logged out successfully"}


# ─────────────────────────────────────────────────────────────────────────────
# Create employee (signup / bulk import)
# DB trigger fires on employees INSERT.
# App-level audit adds source context (signup vs bulk_import).
# ─────────────────────────────────────────────────────────────────────────────

async def create_employee(
    payload,
    current_user_id: str,
    request: Optional[Request] = None,
    source: str = "signup",          # "signup" | "bulk_import"
):
    """
    Persists the employee record.

    Wallet creation REMOVED — the Wallet service listens on the
    'employee.created' Redis Stream event and provisions the wallet
    asynchronously.
    """
    payload.username = payload.username.strip()

    if payload.manager_id:
        if not await db.employees.find_unique(where={"employee_id": str(payload.manager_id)}):
            raise HTTPException(status_code=400, detail="Manager not found")

    if not await db.designations.find_unique(where={"designation_id": str(payload.designation_id)}):
        raise HTTPException(status_code=400, detail="Designation not found")

    if not await db.departments.find_unique(where={"department_id": str(payload.department_id)}):
        raise HTTPException(status_code=400, detail="Department not found")

    active_status = await db.status_master.find_first(where={"status_code": "ACTIVE"})
    if not active_status:
        raise HTTPException(status_code=500, detail="Default ACTIVE status not found")

    new_emp = None
    async with audit_ctx(
        user_id    = current_user_id,
        request    = request,
        table_name = "employees",
        record_id  = lambda: str(new_emp.employee_id) if new_emp else "UNKNOWN",
        operation  = "INSERT",
        new_values = lambda: {
            "username":      new_emp.username if new_emp else "",
            "email":         new_emp.email if new_emp else "",
            "department_id": str(new_emp.department_id) if new_emp else "",
            "designation_id":str(new_emp.designation_id) if new_emp else "",
            "source":        source,
        },
    ):
        new_emp = await db.employees.create(
            data=cast(prisma.types.employeesCreateInput, {
            "username":        payload.username,
            "email":           payload.email,
            "password_hash":   hash_password(payload.password),
            "designation_id":  str(payload.designation_id),
            "department_id":   str(payload.department_id),
            "manager_id":      str(payload.manager_id) if payload.manager_id else None,
            "date_of_joining": _now(),
            "date_of_birth": (
                datetime.combine(payload.date_of_birth, datetime.min.time()).replace(tzinfo=timezone.utc)
                if payload.date_of_birth else None
            ),
            "status_id":  active_status.status_id,
            "created_by": current_user_id,
            "updated_by": current_user_id,
            "updated_at": _now(),
        })
    )

    # Notify downstream services — Wallet provisions asynchronously
    await publish("events:employee.created", {
        "employee_id": str(new_emp.employee_id),
        "created_by":  current_user_id,
    })

    return new_emp


# ─────────────────────────────────────────────────────────────────────────────
# Password reset — request
# No DB write → explicit audit row only.
# We only audit when the user actually exists (no user enumeration in audit log).
# ─────────────────────────────────────────────────────────────────────────────

async def request_password_reset(
    email: str,
    request: Optional[Request] = None,
) -> dict:
    user = await db.employees.find_unique(where={"email": email})
    if user:
        reset_token = create_reset_token(employee_id=str(user.employee_id), email=user.email)
        try:
            send_password_reset_email(
                email=user.email, reset_token=reset_token, username=user.username
            )
        except Exception as exc:
            logger.warning("Failed to send reset email to %s: %s", email, exc)

        # Audit the reset request — performed_by the employee themselves
        await audit(
            table_name   = "employees",
            record_id    = str(user.employee_id),
            operation    = "PASSWORD_RESET_REQUESTED",
            performed_by = str(user.employee_id),
            new_values   = {"email": email},
            request      = request,
        )

    return {"message": "If your email is registered, you will receive a password reset link shortly."}


# ─────────────────────────────────────────────────────────────────────────────
# Password reset — confirm
# DB trigger fires on employees UPDATE (password_hash change).
# DB trigger fires on refresh_tokens UPDATE_MANY (revoke all tokens).
# App-level audit adds explicit PASSWORD_RESET operation on employees table.
# ─────────────────────────────────────────────────────────────────────────────

async def reset_password(
    token: str,
    new_password: str,
    request: Optional[Request] = None,
) -> dict:
    payload = decode_reset_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    employee_id = payload.get("sub")
    email       = payload.get("email")
    if not employee_id or not email:
        raise HTTPException(status_code=400, detail="Invalid token payload")

    user = await db.employees.find_unique(where={"employee_id": employee_id})
    if not user or user.email != email:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    async with audit_ctx(
        user_id    = employee_id,
        request    = request,
        table_name = "employees",
        record_id  = employee_id,
        operation  = "PASSWORD_RESET",
        # Never store old/new password hashes — leave values minimal
        new_values = {"password_changed": True, "all_tokens_revoked": True},
    ):
        await db.employees.update(
            where={"employee_id": str(employee_id)},
            data=cast(prisma.types.employeesUpdateInput, {
                "password_hash": hash_password(new_password),
                "must_change_password": False,
                "updated_at":    _now(),
                "updated_by":    str(employee_id),
            }),
        )

    # Revoke all existing refresh tokens — DB trigger fires per row
    await db.refresh_tokens.update_many(
        where={"employee_id": employee_id, "revoked_at": None},
        data={"revoked_at": _now(), "updated_at": _now()},
    )

    try:
        send_password_reset_confirmation(email=user.email, username=user.username)
    except Exception as exc:
        logger.warning("Failed to send confirmation to %s: %s", email, exc)

    return {"message": "Password reset successful. Please login with your new password."}


# ─────────────────────────────────────────────────────────────────────────────
# Change password (for authenticated user)
# DB trigger fires on employees UPDATE.
# App-level audit adds explicit PASSWORD_CHANGE operation.
# ─────────────────────────────────────────────────────────────────────────────

async def change_password(
    employee_id: str,
    new_password: str,
    request: Optional[Request] = None,
) -> dict:
    user = await db.employees.find_unique(where={"employee_id": employee_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    async with audit_ctx(
        user_id    = employee_id,
        request    = request,
        table_name = "employees",
        record_id  = employee_id,
        operation  = "PASSWORD_CHANGE",
        new_values = {"password_changed": True, "must_change_password": False},
    ):
        await db.employees.update(
            where={"employee_id": employee_id},
            data=cast(prisma.types.employeesUpdateInput,{
                "password_hash": hash_password(new_password),
                "must_change_password": False,
                "updated_at":    _now(),
                "updated_by":    employee_id,
            }),
        )

    return {"message": "Password updated successfully."}