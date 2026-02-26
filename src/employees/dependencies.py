# src/employees/dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials  # ← change this
from src.core.security import decode_token
from src.prisma.client import db
from prisma import Prisma

bearer_scheme = HTTPBearer()  # ← replaces OAuth2PasswordBearer

class CurrentEmployee:
    def __init__(self, id: str, roles: list, email: str):
        self.id = id
        self.roles = roles
        self.email = email

async def get_current_employee(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)  # ← change this
) -> CurrentEmployee:
    payload = decode_token(credentials.credentials)  # ← .credentials extracts the token

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    roles = payload.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]

    return CurrentEmployee(
        id=payload.get("sub"),
        roles=roles,
        email=payload.get("email")
    )

def get_db() -> Prisma:
    return db