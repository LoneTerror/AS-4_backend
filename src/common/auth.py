"""Common authentication and user models"""
from typing import List


class CurrentUser:
    """Current authenticated user model"""
    def __init__(self, id: str, roles: List[str]):
        self.id = id
        self.roles = roles


async def get_current_user() -> CurrentUser:
    """
    Get current authenticated user.
    
    TEMP HARD-CODED USER - Remove this when JWT / Gateway auth is added.
    """
    return CurrentUser(
        id="110e8400-e29b-41d4-a716-446655440000",  # existing employee_id
        roles=["SUPER_ADMIN"]  # change to HR_ADMIN / MANAGER when needed
    )