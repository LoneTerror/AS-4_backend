from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from src.core.security import decode_token

# Matches the router prefix /v1/auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/v1/auth/login")

class CurrentUser:
    def __init__(self, id: str, roles: list):
        self.id = id
        self.roles = roles


async def get_current_user(token: str = Depends(oauth2_scheme)):
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
    async def role_checker(token: str = Depends(oauth2_scheme)):
        payload = decode_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token"
            )

        user_roles = payload.get("roles", [])

        # Super Admin bypass — always allowed
        if "SUPER_ADMIN" in user_roles:
            return payload

        # Check if user has ANY of the allowed roles
        if not any(role in allowed_roles for role in user_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action"
            )

        return payload

    return role_checker