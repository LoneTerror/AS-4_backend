from src.prisma.client import db
from src.core.security import (
    verify_password,
    create_access_token,
    hash_password,
    hash_refresh_token,
    verify_refresh_token,
    decode_token,
    create_reset_token,
    decode_reset_token,
    ACCESS_TOKEN_EXPIRE_MINUTES
)
from src.core.email_utils import send_password_reset_email, send_password_reset_confirmation

from fastapi import HTTPException, status
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import secrets

def _now():
    """Always returns a timezone-aware UTC datetime"""
    return datetime.now(timezone.utc)

# Separator that will NEVER appear in a UUID or token_urlsafe string
_TOKEN_SEP = "||"

# Helper to format the response to match Schema
def _build_login_response(user, access_token, refresh_token_raw):
    return {
        "access_token": access_token,
        "refresh_token": refresh_token_raw,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "employee": {
            "employee_id": user.employee_id,
            "username": user.username,
            "email": user.email,
            "designation_id": user.designation_id,
            "department_id": user.department_id
        }
    }


# -------------------------------
# TOKEN VALIDATION (for other services)
# -------------------------------
async def validate_token(token: str):
    """
    Validate JWT token and return user info.
    Used by other microservices to authenticate requests.
    """
    payload = decode_token(token)

    if not payload:
        return {
            "valid": False,
            "error": "Invalid or expired token"
        }

    return {
        "valid": True,
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "roles": payload.get("roles", []),
        "department_id": payload.get("department_id")
    }


# -------------------------------
# LOGIN
# -------------------------------
async def authenticate_user(username: str, password: str):
    print(f"DEBUG: Attempting login for {username}")

    # 1. Fetch User with roles included
    user = await db.employees.find_first(
        where={
            "OR": [
                {"username": username},
                {"email": username}
            ]
        },
        include={
            "employee_roles_employee_roles_employee_idToemployees": {
                "where": {"is_active": True},
                "include": {"roles": True}
            }
        }
    )

    if not user:
        print("DEBUG: User not found in DB")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 2. Verify Password
    if not verify_password(password, user.password_hash):
        print("DEBUG: Password mismatch")
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # 3. Extract Roles
    roles = []
    try:
        emp_roles = user.employee_roles_employee_roles_employee_idToemployees or []
        for er in emp_roles:
            if er.roles and hasattr(er.roles, "role_code"):
                roles.append(er.roles.role_code)
        print(f"DEBUG: Found roles: {roles}")
    except Exception as e:
        print(f"CRITICAL WARNING: Failed to extract roles. Error: {e}")

    # FIX: Apply fallback AFTER extraction attempt, not inside the except block only
    if not roles:
        roles = ["EMPLOYEE"]

    # 4. Create Access Token
    access_token = create_access_token({
        "sub": str(user.employee_id),
        "email": user.email,
        "roles": roles,
        "department_id": str(user.department_id),
    })

    # 5. Create Refresh Token
    token_id = str(uuid4())
    token_secret = secrets.token_urlsafe(64)

    client_refresh_token = f"{token_id}{_TOKEN_SEP}{token_secret}"

    refresh_token_hash = hash_refresh_token(token_secret)

    await db.refresh_tokens.create(
        data={
            "token_id": token_id,
            "token_hash": refresh_token_hash,
            "employee_id": user.employee_id,
            "expires_at": _now() + timedelta(days=7),
            "created_at": _now(),
            "updated_at": _now(),
        }
    )

    return _build_login_response(user, access_token, client_refresh_token)


# -------------------------------
# REFRESH TOKEN
# -------------------------------
async def refresh_access_token(client_refresh_token: str):
    if _TOKEN_SEP not in client_refresh_token:
        raise HTTPException(status_code=401, detail="Invalid token format")

    token_id, token_secret = client_refresh_token.split(_TOKEN_SEP, 1)

    # 1. Direct Lookup by ID
    stored_token = await db.refresh_tokens.find_unique(
        where={"token_id": token_id},
        include={"employees": True}
    )

    # 2. Validation
    if not stored_token:
        raise HTTPException(status_code=401, detail="Token not found")

    if stored_token.revoked_at or stored_token.expires_at < _now():
        raise HTTPException(status_code=401, detail="Token expired or revoked")

    if not verify_refresh_token(token_secret, stored_token.token_hash):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    user = stored_token.employees

    # 3. Fetch current roles
    # FIX: was `roles = ["EMPLOYEE"]` here, then immediately overwritten by the
    #      list comprehension result — so an empty DB result would wipe the default.
    #      Now we set the fallback AFTER the query.
    roles = []
    try:
        roles_relation = await db.employee_roles.find_many(
            where={
                "employee_id": user.employee_id,
                "is_active": True
            },
            include={"roles": True}
        )
        roles = [
            r.roles.role_code for r in roles_relation
            if r.roles and r.is_active
        ]
    except Exception as e:
        print(f"Refresh Token Role Error: {e}")

    # FIX: Fallback applied after query so it's never silently discarded
    if not roles:
        roles = ["EMPLOYEE"]

    # 4. Create new access token
    new_access_token = create_access_token({
        "sub": str(user.employee_id),
        "email": user.email,
        "roles": roles,
        "department_id": str(user.department_id),
    })

    return _build_login_response(user, new_access_token, client_refresh_token)


# -------------------------------
# LOGOUT
# -------------------------------
async def logout_user(client_refresh_token: str, user_id: str):
    if _TOKEN_SEP not in client_refresh_token:
        return {"message": "Invalid token format, but logged out locally"}

    token_id, token_secret = client_refresh_token.split(_TOKEN_SEP, 1)

    # Only revoke if the token belongs to the requesting user
    stored_token = await db.refresh_tokens.find_first(
        where={
            "token_id": token_id,
            "employee_id": user_id
        }
    )

    if stored_token and verify_refresh_token(token_secret, stored_token.token_hash):
        # FIX: Previously only filtered by token_id, allowing User A to revoke
        # User B's token (horizontal privilege escalation / BOLA).
        # Now employee_id is included in the update where clause so ownership
        # is enforced atomically at the DB level — not just at the find_first level.
        await db.refresh_tokens.update(
            where={"token_id": token_id, "employee_id": user_id},
            data={
                "revoked_at": _now(),
                "updated_at": _now(),
            }
        )

    return {"message": "Logged out successfully"}


# -------------------------------
# CREATE EMPLOYEE
# -------------------------------
async def create_employee(payload, current_user_id: str):
    # Validate manager exists if provided
    if payload.manager_id:
        manager = await db.employees.find_unique(
            where={"employee_id": str(payload.manager_id)}
        )
        if not manager:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager not found"
            )

    # Validate designation exists
    designation = await db.designations.find_unique(
        where={"designation_id": str(payload.designation_id)}
    )
    if not designation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Designation not found"
        )

    # Validate department exists
    department = await db.departments.find_unique(
        where={"department_id": str(payload.department_id)}
    )
    if not department:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department not found"
        )

    active_status = await db.status_master.find_first(
        where={"status_code": "ACTIVE"}
    )
    if not active_status:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default ACTIVE status not found. Please check status_master table."
        )

    # Hash password
    hashed_pwd = hash_password(payload.password)

    # Create employee
    new_emp = await db.employees.create(
        data={
            "username": payload.username,
            "email": payload.email,
            "password_hash": hashed_pwd,
            "designation_id": str(payload.designation_id),
            "department_id": str(payload.department_id),
            "manager_id": str(payload.manager_id) if payload.manager_id else None,
            "date_of_joining": _now(),
            "status_id": active_status.status_id,
            "created_by": current_user_id,
            "updated_by": current_user_id,
            "updated_at": _now()
        }
    )

    # Create wallet for the new employee
    await db.wallets.create(
        data={
            "employee_id": new_emp.employee_id,
            "available_points": 0,
            "redeemed_points": 0,
            "total_earned_points": 0,
            "created_by": current_user_id,
            "updated_by": current_user_id,
            "updated_at": _now()
        }
    )

    return new_emp


# -------------------------------
# FORGOT PASSWORD
# -------------------------------
async def request_password_reset(email: str):
    """
    Request password reset - sends email with reset token.
    Always returns success to prevent email enumeration attacks.
    """

    # 1. Lookup user by email
    user = await db.employees.find_unique(
        where={"email": email}
    )

    # 2. If user exists, generate token and send email
    if user:
        reset_token = create_reset_token(
            employee_id=str(user.employee_id),
            email=user.email
        )

        try:
            send_password_reset_email(
                email=user.email,
                reset_token=reset_token,
                username=user.username
            )
            print(f"✅ Password reset email sent to {user.email}")
        except Exception as e:
            print(f"❌ Failed to send reset email: {e}")
            # Don't raise — still return success response
    else:
        print(f"⚠️ Password reset requested for non-existent email: {email}")

    # 3. Always return success (prevents email enumeration)
    return {
        "message": "If your email is registered, you will receive a password reset link shortly."
    }


# -------------------------------
# RESET PASSWORD
# -------------------------------
async def reset_password(token: str, new_password: str):
    """Reset password using the reset token."""

    # 1. Decode and validate token
    payload = decode_reset_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )

    employee_id = payload.get("sub")
    email = payload.get("email")

    if not employee_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token payload"
        )

    # 2. Verify user still exists
    user = await db.employees.find_unique(
        where={"employee_id": employee_id}
    )

    if not user or user.email != email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )

    # 3. Hash new password
    new_password_hash = hash_password(new_password)

    # 4. Update password
    await db.employees.update(
        where={"employee_id": employee_id},
        data={
            "password_hash": new_password_hash,
            "updated_at": _now(),
            "updated_by": employee_id  # Self-updated
        }
    )

    # 5. Revoke all existing refresh tokens — force re-login with new password
    await db.refresh_tokens.update_many(
        where={
            "employee_id": employee_id,
            "revoked_at": None
        },
        data={
            "revoked_at": _now(),
            "updated_at": _now()
        }
    )

    # 6. Send confirmation email
    try:
        send_password_reset_confirmation(
            email=user.email,
            username=user.username
        )
    except Exception as e:
        print(f"⚠️ Failed to send confirmation email: {e}")

    print(f"✅ Password reset successful for user: {user.username}")

    return {
        "message": "Password reset successful. Please login with your new password."
    }