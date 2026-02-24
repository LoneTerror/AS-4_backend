# from fastapi import Depends, HTTPException, status
# from fastapi.security import OAuth2PasswordBearer
# from src.core.security import decode_token

# oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/v1/auth/login")

# class CurrentEmployee:
#     def __init__(self, id: str, roles: list, email: str):
#         self.id = id
#         self.roles = roles
#         self.email = email

# async def get_current_employee(token: str = Depends(oauth2_scheme)) -> CurrentEmployee:
#     payload = decode_token(token)

#     if not payload:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail="Invalid or expired token",
#             headers={"WWW-Authenticate": "Bearer"},
#         )

#     # Ensure roles is a list (handles some tokens storing it as string)
#     roles = payload.get("roles", [])
#     if isinstance(roles, str):
#         roles = [roles]

#     return CurrentEmployee(
#         id=payload.get("sub"),
#         roles=roles,
#         email=payload.get("email")
#     )

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from src.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/v1/auth/login")

class CurrentEmployee:
    def __init__(self, id: str, roles: list, email: str):
        self.id = id
        self.roles = roles
        self.email = email

async def get_current_employee(token: str = Depends(oauth2_scheme)) -> CurrentEmployee:
    # Safely decode the token to prevent 500 crashes on expired tokens
    try:
        payload = decode_token(token)
    except Exception as e:
        print(f"Token validation failed: {e}")
        payload = None

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Ensure roles is a list (handles some tokens storing it as string)
    roles = payload.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]

    return CurrentEmployee(
        id=payload.get("sub"),
        roles=roles,
        email=payload.get("email")
    )