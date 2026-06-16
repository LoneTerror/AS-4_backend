"""
src/auth/router.py
"""
from __future__ import annotations

import csv
import io
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from fastapi.security import OAuth2PasswordBearer

from src.auth.schemas import (
    EmployeeResponse, ForgotPasswordRequest, ForgotPasswordResponse,
    LoginRequest, LogoutRequest, RefreshRequest, ResetPasswordRequest,
    ResetPasswordResponse, SignUpRequest, TokenResponse,
    TokenValidationRequest, TokenValidationResponse,
)
from src.auth.service import (
    authenticate_user, create_employee, logout_user,
    refresh_access_token, request_password_reset, reset_password, validate_token,
)
from src.common.dependencies import check_route_permission, CurrentUser
from src.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/aabhar/v1/auth/login")
router        = APIRouter()

REQUIRED_COLUMNS = {"username", "email", "password", "designation_id", "department_id"}


def _parse_csv(content: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))


def _parse_xlsx(content: bytes) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(status_code=500, detail="openpyxl not installed")
    wb   = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    return [
        {headers[i]: (str(c).strip() if c is not None else "")
         for i, c in enumerate(row)}
        for row in rows[1:]
    ]


def _row_to_signup(row: dict) -> tuple[Optional[SignUpRequest], Optional[str]]:
    row     = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
    missing = REQUIRED_COLUMNS - set(row.keys())
    if missing:
        return None, f"Missing columns: {', '.join(sorted(missing))}"
    for col in REQUIRED_COLUMNS:
        if not row.get(col):
            return None, f"'{col}' is empty"
    try:
        return SignUpRequest(
            username=row["username"],
            email=row["email"],
            password=row["password"],
            designation_id=UUID(row["designation_id"]),
            department_id=UUID(row["department_id"]),
            manager_id=UUID(row["manager_id"]) if row.get("manager_id") else None,
            date_of_birth=row["date_of_birth"] if row.get("date_of_birth") else None,
        ), None
    except Exception as exc:
        return None, str(exc)


# ── Public endpoints (no auth required) ──────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,          # needed for IP / user-agent in audit log
    payload: LoginRequest,
):
    return await authenticate_user(payload.username, payload.password, request)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    # Refresh is stateless — no user context to audit beyond what the
    # DB trigger already captures on refresh_tokens reads.
    return await refresh_access_token(payload.refresh_token)


@router.post("/logout")
async def logout(
    request: Request,
    payload: LogoutRequest,
    token: str = Depends(oauth2_scheme),
):
    user_data = decode_token(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    return await logout_user(payload.refresh_token, user_data["sub"], request)


@router.post("/validate", response_model=TokenValidationResponse)
async def validate_token_endpoint(payload: TokenValidationRequest):
    return await validate_token(payload.token)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
):
    return await request_password_reset(payload.email, request)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password_endpoint(
    request: Request,
    payload: ResetPasswordRequest,
):
    return await reset_password(payload.token, payload.new_password, request)


# ── Protected endpoints ───────────────────────────────────────────────────────

@router.post("/signup", response_model=EmployeeResponse)
async def signup(
    request: Request,
    payload: SignUpRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create employee. Wallet provisioned asynchronously via Redis Stream event."""
    return await create_employee(payload, current_user.id, request, source="signup")


@router.post(
    "/bulk-import",
    status_code=status.HTTP_200_OK,
    summary="Bulk import employees via CSV or XLSX",
)
async def bulk_import_employees(
    request: Request,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(check_route_permission),
):
    """
    Each successful row publishes an employee.created event so the
    Wallet service provisions wallets asynchronously.
    Each row is audited individually with source='bulk_import'.
    """
    filename = (file.filename or "").lower()
    if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
        raise HTTPException(status_code=400, detail="Only .csv and .xlsx are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="File is empty")

    try:
        rows = _parse_csv(content) if filename.endswith(".csv") else _parse_xlsx(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Parse error: {exc}")

    if not rows:
        raise HTTPException(status_code=400, detail="File has no data rows")

    results, succeeded, failed = [], 0, 0

    for idx, row in enumerate(rows, start=2):
        payload, err = _row_to_signup(row)
        if err:
            failed += 1
            results.append({
                "row":      idx,
                "username": row.get("username"),
                "email":    row.get("email"),
                "status":   "error",
                "error":    err,
            })
            continue
        try:
            emp = await create_employee(
                payload, current_user.id, request, source="bulk_import"
            )
            succeeded += 1
            results.append({
                "row":         idx,
                "username":    emp.username,
                "email":       emp.email,
                "status":      "success",
                "employee_id": str(emp.employee_id),
            })
        except HTTPException as exc:
            failed += 1
            results.append({
                "row":      idx,
                "username": payload.username,
                "email":    payload.email,
                "status":   "error",
                "error":    exc.detail,
            })
        except Exception as exc:
            failed += 1
            results.append({
                "row":      idx,
                "username": payload.username,
                "email":    payload.email,
                "status":   "error",
                "error":    str(exc),
            })

    return {
        "total":     len(rows),
        "succeeded": succeeded,
        "failed":    failed,
        "results":   results,
    }