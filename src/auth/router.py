# src/auth/router.py

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from uuid import UUID
import csv
import io

from src.auth.schemas import (
    LoginRequest,
    TokenResponse,
    SignUpRequest,
    LogoutRequest,
    RefreshRequest,
    EmployeeResponse,
    TokenValidationRequest,
    TokenValidationResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from src.auth.service import (
    authenticate_user,
    create_employee,
    logout_user,
    refresh_access_token,
    validate_token,
    request_password_reset,
    reset_password,
)
from src.common.dependencies import check_route_permission, CurrentUser
from src.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")

router = APIRouter()


# ---------------------------------------------------------------------------
# Bulk import helpers
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {"username", "email", "password", "designation_id", "department_id"}


def _parse_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def _parse_xlsx(content: bytes) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="openpyxl is not installed. Add it to requirements.txt.",
        )
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    return [
        {headers[i]: (str(cell).strip() if cell is not None else "")
         for i, cell in enumerate(row)}
        for row in rows[1:]
    ]


def _row_to_signup(row: dict) -> tuple[Optional[SignUpRequest], Optional[str]]:
    row = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}

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
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """Login endpoint - returns access and refresh tokens"""
    return await authenticate_user(payload.username, payload.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest):
    """Refresh access token using refresh token"""
    return await refresh_access_token(payload.refresh_token)


@router.post("/logout")
async def logout(
    payload: LogoutRequest,
    token: str = Depends(oauth2_scheme),
):
    """Logout - revokes the refresh token"""
    user_data = decode_token(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    return await logout_user(payload.refresh_token, user_data["sub"])


@router.post("/signup", response_model=EmployeeResponse)
async def signup(
    payload: SignUpRequest,
    current_user: CurrentUser = Depends(check_route_permission),
):
    """Create a new employee."""
    return await create_employee(payload, current_user.id)


@router.post("/validate", response_model=TokenValidationResponse)
async def validate_token_endpoint(payload: TokenValidationRequest):
    """Validate JWT token - used by other microservices"""
    return await validate_token(payload.token)


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(payload: ForgotPasswordRequest):
    """Request password reset - always returns success to prevent email enumeration"""
    return await request_password_reset(payload.email)


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password_endpoint(payload: ResetPasswordRequest):
    """Reset password using reset token from email"""
    return await reset_password(payload.token, payload.new_password)


# ---------------------------------------------------------------------------
# Bulk Import
# ---------------------------------------------------------------------------

@router.post(
    "/bulk-import",
    summary="Bulk import employees via CSV or XLSX",
    description="""
Upload a **CSV** or **XLSX** file to create multiple employees at once.
Each row is processed through the same logic as `POST /signup`.
Rows that fail are recorded in the response — the rest are still created (partial success).

**Required columns (case-insensitive):**
`username`, `email`, `password`, `designation_id`, `department_id`

**Optional columns:** `manager_id`
    """,
    status_code=status.HTTP_200_OK,
)
async def bulk_import_employees(
    file: UploadFile = File(..., description="CSV or XLSX file with employee data"),
    current_user: CurrentUser = Depends(check_route_permission),
):
    filename = (file.filename or "").lower()
    if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv and .xlsx files are supported.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        rows = _parse_csv(content) if filename.endswith(".csv") else _parse_xlsx(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse file: {e}",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File contains no data rows.",
        )

    results = []
    succeeded = 0
    failed = 0

    for idx, row in enumerate(rows, start=2):
        signup_payload, parse_error = _row_to_signup(row)

        if parse_error:
            failed += 1
            results.append({
                "row":      idx,
                "username": row.get("username") or row.get("Username"),
                "email":    row.get("email") or row.get("Email"),
                "status":   "error",
                "error":    parse_error,
            })
            continue

        try:
            emp = await create_employee(signup_payload, current_user.id)
            succeeded += 1
            results.append({
                "row":         idx,
                "username":    emp.username,
                "email":       emp.email,
                "status":      "success",
                "employee_id": str(emp.employee_id),
            })
        except HTTPException as e:
            failed += 1
            results.append({
                "row":      idx,
                "username": signup_payload.username,
                "email":    signup_payload.email,
                "status":   "error",
                "error":    e.detail,
            })
        except Exception as e:
            failed += 1
            results.append({
                "row":      idx,
                "username": signup_payload.username,
                "email":    signup_payload.email,
                "status":   "error",
                "error":    str(e),
            })

    return {
        "total":     len(rows),
        "succeeded": succeeded,
        "failed":    failed,
        "results":   results,
    }