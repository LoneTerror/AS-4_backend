# src/common/audit.py
#
# Banking-grade audit layer for HDFC RnR.
#
# TWO layers work together:
#
#   Layer 1 — DB trigger (migration.sql)
#     Fires on every INSERT/UPDATE/DELETE at Postgres level regardless of
#     what caused the write. Tamper-proof, catches DBA hotfixes, migrations,
#     background consumers. Reads session variables set by Layer 2.
#
#   Layer 2 — This module
#     Sets the Postgres session variables the trigger reads (user_id, IP,
#     user-agent) and writes a richer app-level record with business context
#     (operation semantics like "REDEEM", "RESTOCK", "REVOKE" that the
#     trigger can't infer from TG_OP alone).
#
# USAGE in any service write function:
#
#   from src.common.audit import audit_ctx
#
#   async def create_department(data, created_by_id, request=None):
#       new_dept = None
#       async with audit_ctx(
#           user_id    = created_by_id,
#           request    = request,
#           table_name = "departments",
#           record_id  = lambda: str(new_dept.department_id),
#           operation  = "INSERT",
#           new_values = lambda: new_dept.model_dump(),
#       ):
#           new_dept = await db.departments.create(data={...})
#
# The context manager:
#   1. Sets Postgres session variables BEFORE the body runs
#      -> trigger picks them up on the write inside
#   2. After the write succeeds writes the richer app-level audit row
#   3. Never raises — audit failures are logged and swallowed
#
# For background consumers (no Request):
#   async with audit_ctx(user_id=employee_id, request=None, ...):
#       ...
#   ip_address and user_agent will be NULL in both trigger and app rows.

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional, Union

from fastapi import Request
from prisma import Json

from src.prisma.client import db, set_audit_context

logger = logging.getLogger(__name__)

# Sentinel UUID — used by the trigger when no session context is set.
# Must match migration.sql.
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"

# Fields that must never appear in audit storage
_SENSITIVE = frozenset({"password_hash", "token_hash", "replaced_by_token"})


# ─────────────────────────────────────────────────────────────────────────────
# Public context manager
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def audit_ctx(
    *,
    user_id:    str,
    table_name: str,
    operation:  str,
    record_id:  Union[str, Callable[[], str]],
    new_values: Union[None, dict, Callable[[], Optional[dict]]] = None,
    old_values: Union[None, dict, Callable[[], Optional[dict]]] = None,
    request:    Optional[Request] = None,
    # Optional raw IP override — use when no Request is available but the
    # caller has the originating IP (e.g. passed through a Redis stream payload).
    # Ignored when request is provided (request takes precedence).
    ip_address: Optional[str] = None,
):
    """
    Async context manager that:
      1. Sets Postgres session variables so the DB trigger captures user
         context on every write that happens inside the `async with` block.
      2. After the block succeeds, writes the richer app-level audit row
         with business-semantic operation types (RESTOCK, REDEEM, REVOKE…).
      3. Never propagates audit exceptions — business logic always wins.

    Example — INSERT (record_id not known until after the write):
        new_dept = None
        async with audit_ctx(
            user_id    = current_user.id,
            request    = request,
            table_name = "departments",
            record_id  = lambda: str(new_dept.department_id),
            operation  = "INSERT",
            new_values = lambda: new_dept.model_dump(),
        ):
            new_dept = await db.departments.create(data={...})

    Example — UPDATE (record_id known upfront, old_values captured before):
        old = (await db.employees.find_unique(where={"employee_id": eid})).model_dump()
        updated = None
        async with audit_ctx(
            user_id    = current_user.id,
            request    = request,
            table_name = "employees",
            record_id  = eid,
            operation  = "UPDATE",
            old_values = old,
            new_values = lambda: updated.model_dump(),
        ):
            updated = await db.employees.update(where=..., data=...)
    """
    req_ip, user_agent = _extract_request_info(request)
    # request takes precedence; ip_address kwarg is the consumer fallback
    resolved_ip = req_ip if request is not None else ip_address

    # Step 1 — push context to Postgres so the trigger knows who is acting
    try:
        await set_audit_context(
            user_id    = user_id,
            ip_address = resolved_ip,
            user_agent = user_agent,
        )
    except Exception as exc:
        logger.error(
            "set_audit_context failed — DB trigger will use sentinel UUID | %s", exc
        )

    # Step 2 — yield: the caller's DB write happens here
    try:
        yield
    except Exception:
        # Business exception — clear context best-effort, then re-raise
        try:
            await set_audit_context(user_id=SYSTEM_USER_ID)
        except Exception:
            pass
        raise

    # Step 3 — write the richer app-level audit row (non-fatal)
    await _write_app_audit(
        table_name   = table_name,
        record_id    = _resolve(record_id),
        operation    = operation,
        performed_by = user_id,
        old_values   = _resolve(old_values),
        new_values   = _resolve(new_values),
        ip_address   = resolved_ip,
        user_agent   = user_agent,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Standalone write — for pure business events with no single-table DB write
# e.g. failed login attempts, password reset requests
# ─────────────────────────────────────────────────────────────────────────────

async def audit(
    *,
    table_name:   str,
    record_id:    str,
    operation:    str,
    performed_by: str,
    old_values:   Optional[dict[str, Any]] = None,
    new_values:   Optional[dict[str, Any]] = None,
    request:      Optional[Request] = None,
) -> None:
    """
    Write one app-level audit row directly without setting session variables.
    Use audit_ctx() for normal service writes.
    Use this for events like LOGIN_FAILED, TOKEN_REVOKED, PASSWORD_RESET.
    Never raises.
    """
    ip_address, user_agent = _extract_request_info(request)
    await _write_app_audit(
        table_name   = table_name,
        record_id    = record_id,
        operation    = operation,
        performed_by = performed_by,
        old_values   = old_values,
        new_values   = new_values,
        ip_address   = ip_address,
        user_agent   = user_agent,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _write_app_audit(
    *,
    table_name:   str,
    record_id:    str,
    operation:    str,
    performed_by: str,
    old_values:   Optional[dict],
    new_values:   Optional[dict],
    ip_address:   Optional[str],
    user_agent:   Optional[str],
) -> None:
    try:
        await db.audit_log.create(
            data={
                "table_name":     table_name,
                "record_id":      record_id,
                "operation_type": operation.upper(),
                "performed_by":   performed_by,
                "ip_address":     ip_address,
                "user_agent":     user_agent,
                "old_values":     Json(_sanitise(old_values)),
                "new_values":     Json(_sanitise(new_values)),
            }
        )
    except Exception as exc:
        logger.error(
            "app audit_log write failed | table=%s record=%s op=%s by=%s | %s",
            table_name, record_id, operation, performed_by, exc,
            exc_info=True,
        )


def _extract_request_info(
    request: Optional[Request],
) -> tuple[Optional[str], Optional[str]]:
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    if request is not None:
        try:
            # Prefer forwarded headers set by a reverse proxy (nginx, Caddy, etc.)
            # X-Forwarded-For may be a comma-separated chain — take the first (client) IP.
            forwarded_for = request.headers.get("x-forwarded-for")
            real_ip       = request.headers.get("x-real-ip")
            if forwarded_for:
                ip_address = forwarded_for.split(",")[0].strip()
            elif real_ip:
                ip_address = real_ip.strip()
            else:
                ip_address = request.client.host if request.client else None
        except Exception:
            pass
        try:
            user_agent = request.headers.get("user-agent")
        except Exception:
            pass
    return ip_address, user_agent


def _resolve(value: Any) -> Any:
    """Resolve a callable or return a plain value as-is."""
    return value() if callable(value) else value


def _sanitise(values: Optional[dict[str, Any]]) -> dict[str, Any]:
    """
    Prepare a dict for JSON storage:
    - None input → {}
    - Strip sensitive fields
    - Coerce UUID / datetime / Decimal to JSON-safe types
    """
    if not values:
        return {}

    def _coerce(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, (bool, int, float, str)):
            return v
        if isinstance(v, dict):
            return {k: _coerce(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_coerce(i) for i in v]
        import uuid
        import datetime as _dt
        from decimal import Decimal
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, (_dt.datetime, _dt.date)):
            return v.isoformat()
        if isinstance(v, Decimal):
            return float(v)
        return str(v)

    return {
        k: _coerce(v)
        for k, v in values.items()
        if k not in _SENSITIVE
    }