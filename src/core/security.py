from datetime import datetime, timedelta, timezone
import jwt  
from jwt.exceptions import PyJWTError, ExpiredSignatureError, InvalidTokenError  
import bcrypt
import os
import hashlib
from typing import Optional

# Import your custom logger
from src.core.logger import logger

# ================================
# CONFIGURATION
# ================================

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    # In a microservice, if one pod has a different SECRET_KEY than the Auth service,
    # all tokens will fail signature verification.
    raise RuntimeError("SECRET_KEY environment variable must be set")

ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 30
RESET_TOKEN_EXPIRE_MINUTES = 15 


# ================================
# PASSWORD & REFRESH HASHING
# ================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def verify_refresh_token(token: str, stored_hash: str) -> bool:
    return hash_refresh_token(token) == stored_hash


# ================================
# JWT ACCESS TOKENS
# ================================

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
        "iss": "employee-rewards-system"
    })

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decodes the JWT and logs specific reasons for failure to help debug
    microservice synchronization issues.
    """
    try:
        # Add 30 seconds of leeway for clock drift
        return jwt.decode(
            token, 
            SECRET_KEY, 
            algorithms=[ALGORITHM], 
            leeway=30 
        )
    except ExpiredSignatureError:
        logger.warning("JWT Validation failed: Token has expired")
        return None
    except InvalidTokenError as e:
        # This is where you'll see "Signature verification failed" 
        # in kubectl logs if your SECRET_KEY is out of sync.
        logger.warning(f"JWT Validation failed: {str(e)}")
        return None
    except PyJWTError as e:
        logger.error(f"Unexpected JWT error: {str(e)}")
        return None


# ================================
# PASSWORD RESET TOKENS
# ================================

def create_reset_token(employee_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {
        "sub": employee_id,
        "email": email,
        "purpose": "password_reset",
        "iat": now,
        "exp": now + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        "iss": "employee-rewards-system"
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_reset_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        if payload.get("purpose") != "password_reset":
            logger.warning("Reset token failed: purpose mismatch")
            return None
            
        return payload
    except ExpiredSignatureError:
        logger.warning("Reset token failed: expired")
        return None
    except InvalidTokenError as e:
        logger.warning(f"Reset token failed: {str(e)}")
        return None