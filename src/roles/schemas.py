# src/roles/schemas.py

from pydantic import BaseModel
from typing import Optional


class CreateRoleRequest(BaseModel):
    role_name:   str
    role_code:   str
    description: Optional[str] = None


class AssignRoleRequest(BaseModel):
    employee_id: str
    role_id:     str


class RevokeRoleRequest(BaseModel):
    employee_id: str
    role_id:     str


class SetRoutePermissionRequest(BaseModel):
    route_key: str            # e.g. "POST:/v1/rewards/grant"
    role_id:   str
    title:     Optional[str] = None   # Human-readable label shown in the UI


class DeleteRoutePermissionRequest(BaseModel):
    route_key: str
    role_id:   str


class UpdateRouteTitleRequest(BaseModel):
    route_key: str
    title:     str   # Required — use this endpoint specifically to set/update the label