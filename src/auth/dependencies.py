from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from src.core.security import decode_token

# Matches the router prefix /v1/auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/v1/auth/login")


class CurrentUser:
    def __init__(self, id: str, roles: list):
        self.id = id
        self.roles = roles


async def get_current_user(token: str = Depends(oauth2_scheme)) -> CurrentUser:
    payload = decode_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    return CurrentUser(
        id=payload["sub"],
        roles=payload.get("roles", [])
    )


def require_roles(*allowed_roles):
    """
    Dependency that validates the bearer token and enforces role access.

    FIX: Previously returned the raw JWT payload dict, while get_current_user
    returned a CurrentUser object — making the two dependencies incompatible if
    ever mixed up (one uses user["sub"], the other user.id).

    Now require_roles also returns a CurrentUser object so both dependencies
    are interchangeable and callers always use user.id / user.roles consistently.
    """
    async def role_checker(token: str = Depends(oauth2_scheme)) -> CurrentUser:
        payload = decode_token(token)

        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        user_roles = payload.get("roles", [])

        # Super Admin bypass — always allowed
        if "SUPER_ADMIN" in user_roles:
            return CurrentUser(id=payload["sub"], roles=user_roles)

        # Check if user has ANY of the allowed roles
        if not any(role in allowed_roles for role in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action"
            )

        return CurrentUser(id=payload["sub"], roles=user_roles)

    return role_checker