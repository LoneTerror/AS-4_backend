"""
src/common/internal_client.py ──────────────────────────────
Async HTTP client for internal service-to-service calls.

Drop this in src/common/ — every service that needs to call another service
imports from here.

All base URLs come from env vars so no hostnames are hardcoded.

Environment variables ─────────────────────
  WALLET_SERVICE_URL        http://wallet-service:8006
  RECOGNITION_SERVICE_URL   http://recognition-service:8005
  EMPLOYEES_SERVICE_URL     http://employee-service:8003
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

_WALLET_URL      = os.getenv("WALLET_SERVICE_URL",      "http://localhost:8004")
_RECOGNITION_URL = os.getenv("RECOGNITION_SERVICE_URL", "http://localhost:8005")
_EMPLOYEES_URL   = os.getenv("EMPLOYEES_SERVICE_URL",   "http://localhost:8003")

# One shared client — connection pooling, keep-alive across requests
_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
)


async def close() -> None:
    """Drain the connection pool on app shutdown."""
    await _client.aclose()


# ── Private helpers ───────────────────────────────────────────────────────────

async def _get(url: str, params: dict | None = None) -> Any:
    try:
        resp = await _client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Internal GET %s -> %s", url, exc.response.status_code)
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        )
    except httpx.RequestError as exc:
        logger.error("Internal GET %s unreachable: %s", url, exc)
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {url}")


async def _post(url: str, json: dict) -> Any:
    try:
        resp = await _client.post(url, json=json)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=exc.response.text,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Upstream unavailable: {url}")


# ── Wallet service internal endpoints ─────────────────────────────────────────

async def get_wallet_by_employee(employee_id: str) -> dict:
    """GET /internal/wallets/by-employee/{employee_id}"""
    return await _get(f"{_WALLET_URL}/internal/wallets/by-employee/{employee_id}")


async def get_wallet_by_id(wallet_id: str) -> dict:
    """GET /internal/wallets/by-id/{wallet_id}"""
    return await _get(f"{_WALLET_URL}/internal/wallets/by-id/{wallet_id}")


async def get_wallet_stats(employee_id: str) -> dict:
    """
    GET /internal/wallets/stats?employee_id=...
    Returns: {available_points, total_earned_points,
               pts_this_month, pts_last_month,
               rewards_total, rewards_this_month, rewards_last_month}
    """
    return await _get(
        f"{_WALLET_URL}/internal/wallets/stats",
        params={"employee_id": employee_id},
    )


async def get_wallet_stats_batch(employee_ids: list[str]) -> dict:
    """
    GET /internal/wallets/stats/batch?employee_ids=id1,id2,...
    Returns a dict keyed by employee_id with the same shape as get_wallet_stats.
    Use this instead of calling get_wallet_stats in a loop.
    """
    if not employee_ids:
        return {}
    return await _get(
        f"{_WALLET_URL}/internal/wallets/stats/batch",
        params={"employee_ids": ",".join(employee_ids)},
    )


async def get_leaderboard_data(limit: int = 10) -> list:
    """GET /internal/wallets/leaderboard?limit=..."""
    return await _get(
        f"{_WALLET_URL}/internal/wallets/leaderboard",
        params={"limit": limit},
    )


# ── Recognition service internal endpoints ────────────────────────────────────

async def get_review_stats(employee_id: str) -> dict:
    """
    GET /internal/reviews/stats?employee_id=...
    Returns: {reviews_total, reviews_this_month, reviews_last_month}
    """
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/stats",
        params={"employee_id": employee_id},
    )


async def get_review_stats_batch(employee_ids: list[str]) -> dict:
    """
    GET /internal/reviews/stats/batch?employee_ids=id1,id2,...
    Returns a dict keyed by employee_id with the same shape as get_review_stats.
    Use this instead of calling get_review_stats in a loop.
    """
    if not employee_ids:
        return {}
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/stats/batch",
        params={"employee_ids": ",".join(employee_ids)},
    )


async def get_recent_reviews(employee_id: str, limit: int = 5) -> list:
    """GET /internal/reviews/recent?employee_id=...&limit=..."""
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/recent",
        params={"employee_id": employee_id, "limit": limit},
    )


async def get_recognition_trend(range_: str) -> dict:
    """GET /internal/reviews/trend?range=..."""
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/trend",
        params={"range": range_},
    )


async def get_recognition_by_user(range_: str, page: int, limit: int) -> dict:
    """GET /internal/reviews/by-user?range=...&page=...&limit=..."""
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/by-user",
        params={"range": range_, "page": page, "limit": limit},
    )


async def get_recognition_by_team(range_: str, page: int, limit: int) -> dict:
    """GET /internal/reviews/by-team?range=...&page=...&limit=..."""
    return await _get(
        f"{_RECOGNITION_URL}/internal/reviews/by-team",
        params={"range": range_, "page": page, "limit": limit},
    )


async def get_participation_overview() -> dict:
    """GET /internal/reviews/participation"""
    return await _get(f"{_RECOGNITION_URL}/internal/reviews/participation")


# ── Employees service internal endpoints ─────────────────────────────────────

async def get_active_users_count() -> dict:
    """
    GET /internal/employees/active-count
    Returns: {now: int, last_month: int}
    """
    return await _get(f"{_EMPLOYEES_URL}/internal/employees/active-count")


async def get_departments_with_members() -> list:
    """
    GET /internal/employees/departments-with-members
    Returns all departments with their member list so Analytics can build
    team reports without importing Prisma directly.

    Response: [{department_id, department_name, members: [{employee_id,
                username, designation_name}]}]
    """
    return await _get(f"{_EMPLOYEES_URL}/internal/employees/departments-with-members")


async def get_employee_manager_email(employee_id: str) -> str | None:
    """
    GET /internal/employees/{employee_id}/manager-email

    Returns the email address of the given employee's direct manager,
    or None if the employee has no manager (manager_id IS NULL) or the
    endpoint returns 404.

    Expected success response: {"email": "manager@example.com"}
    Expected no-manager response: 404  (treated as None, not an error)
    """
    try:
        data = await _get(
            f"{_EMPLOYEES_URL}/internal/employees/{employee_id}/manager-email"
        )
        return data.get("email") or None
    except HTTPException as exc:
        if exc.status_code == 404:
            # Employee exists but has no manager — caller should send without CC
            return None
        raise