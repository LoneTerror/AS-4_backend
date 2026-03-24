# src/webhooks/router.py
"""
Webhooks router — thin HTTP layer only.
All business logic lives in src/webhooks/service.py.
Mounted inside Employee Service (src/employees/main.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from prisma import Prisma

from src.common.dependencies import check_route_permission, CurrentUser
from src.prisma.client import db
from src.webhooks import service
from src.webhooks.schemas import HrisWebhookEvent, WebhookResponse


def get_db() -> Prisma:
    return db


router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post(
    "/hris",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="HRIS push webhook",
)
async def hris_webhook(
    request: Request,
    event:   HrisWebhookEvent,
    db:      Prisma         = Depends(get_db),
    _:       CurrentUser    = Depends(check_route_permission),
):
    """
    Receives HRIS push events and syncs employee data.

    Supported events:
      - employee.created
      - employee.updated
      - employee.status_changed

    Security: HMAC-SHA256 signature verified from X-Webhook-Signature header.
    Idempotency: supply event_id in payload to prevent duplicate processing.
    """
    result = await service.handle_hris_event(request, event, db)
    return WebhookResponse(**result)
