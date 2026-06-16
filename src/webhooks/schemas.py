# src/webhooks/schemas.py
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr


class HrisEmployeeCreatedPayload(BaseModel):
    external_id:      str
    username:         str
    email:            EmailStr
    department_code:  str
    designation_code: str
    date_of_joining:  str
    date_of_birth:    Optional[str]       = None
    manager_email:    Optional[EmailStr]  = None


class HrisEmployeeUpdatedPayload(BaseModel):
    email:            EmailStr
    department_code:  Optional[str]       = None
    designation_code: Optional[str]       = None
    manager_email:    Optional[EmailStr]  = None
    date_of_birth:    Optional[str]       = None


class HrisEmployeeStatusPayload(BaseModel):
    email:       EmailStr
    status_code: str


class HrisWebhookEvent(BaseModel):
    event_id: Optional[str] = None   # idempotency key — HRIS should send this
    event:    str
    data:     dict


class WebhookResponse(BaseModel):
    received: bool
    event:    str
