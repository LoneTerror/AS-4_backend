from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
import bcrypt
import os
import hashlib

# ================================
# CONFIGURATION
# ================================

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RESET_TOKEN_EXPIRE_MINUTES = 15  # Short-lived reset token


# ================================
# PASSWORD HASHING (bcrypt)
# ================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify plaintext password against bcrypt hash.
    Compatible with Python bcrypt and Node bcryptjs.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def hash_password(password: str) -> str:
    """
    Hash password using bcrypt.
    Cost factor 12 recommended for production.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


# ================================
# REFRESH TOKEN HASHING (SHA256)
# ================================

def hash_refresh_token(token: str) -> str:
    """
    Hash refresh token using SHA256.
    Refresh tokens are high entropy and do NOT require bcrypt.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_refresh_token(token: str, stored_hash: str) -> bool:
    """
    Compare refresh token with stored SHA256 hash.
    """
    return hash_refresh_token(token) == stored_hash


# ================================
# JWT ACCESS TOKENS
# ================================

def create_access_token(data: dict) -> str:
    """
    Create JWT access token.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "iss": "employee-rewards-system"
    })

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    """
    Decode JWT token.
    Returns payload or None.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ================================
# PASSWORD RESET TOKENS
# ================================

def create_reset_token(employee_id: str, email: str) -> str:
    """
    Create short-lived JWT token for password reset.
    Valid for 15 minutes only.
    """
    to_encode = {
        "sub": employee_id,
        "email": email,
        "purpose": "password_reset",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        "iss": "employee-rewards-system"
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_reset_token(token: str):
    """
    Decode and validate password reset token.
    Returns payload if valid, None otherwise.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Validate purpose
        if payload.get("purpose") != "password_reset":
            return None
            
        return payload
    except JWTError:
        return None