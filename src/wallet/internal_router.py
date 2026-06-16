"""
src/wallet/internal_router.py
──────────────────────────────
Internal-only endpoints consumed by Analytics and Rewards services.

ROUTING NOTE — why routes are written as /internal/wallets/...
───────────────────────────────────────────────────────────────
FastAPI's `root_path` is OpenAPI/docs metadata only. It does NOT
affect route matching. Uvicorn receives the raw path the client sent.

The internal_client calls:
    http://localhost:8006/internal/wallets/stats
    http://localhost:8006/internal/wallets/stats/batch   ← NEW
    http://localhost:8006/internal/wallets/leaderboard
    http://localhost:8006/internal/wallets/by-employee/{id}

In wallet/main.py:  app.include_router(internal_router)   ← no prefix
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, HTTPException, Query

from src.prisma.client import db

router = APIRouter(tags=["Internal"])


@router.get("/internal/employees/{employee_id}/manager-email")
async def get_manager_email(employee_id: str):
    """
    Returns {"email": "manager@example.com"} if the employee has a manager,
    or 404 if manager_id IS NULL.

    Called by internal_client.get_employee_manager_email() which is used
    by the email worker to CC the manager on REVIEW and REWARD notifications.
    """
    from fastapi import HTTPException

    emp = await db.employees.find_unique(where={"employee_id": employee_id})
    if emp is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.manager_id is None:
        raise HTTPException(status_code=404, detail="Employee has no manager")

    manager = await db.employees.find_unique(
        where={"employee_id": str(emp.manager_id)}
    )
    if manager is None:
        raise HTTPException(status_code=404, detail="Manager not found")

    return {"email": manager.email}



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_range(dt: datetime):
    start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, start + relativedelta(months=1)


@router.get("/internal/wallets/by-employee/{employee_id}")
async def get_wallet_by_employee(employee_id: str):
    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {
        "wallet_id":           str(wallet.wallet_id),
        "employee_id":         employee_id,
        "available_points":    wallet.available_points,
        "redeemed_points":     wallet.redeemed_points,
        "total_earned_points": wallet.total_earned_points,
    }


@router.get("/internal/wallets/stats")
async def get_wallet_stats(employee_id: str = Query(...)):
    now        = _now()
    start_this, end_this = _month_range(now)
    start_last, end_last = _month_range(now - relativedelta(months=1))

    wallet = await db.wallets.find_first(where={"employee_id": employee_id})
    if not wallet:
        return {
            "available_points": 0, "total_earned_points": 0,
            "pts_this_month": 0,   "pts_last_month": 0,
            "rewards_total": 0,    "rewards_this_month": 0, "rewards_last_month": 0,
        }

    credit_types = await db.transaction_types.find_many(where={"is_credit": True})
    credit_ids   = [t.type_id for t in credit_types]

    if credit_ids:
        txns_this, txns_last = await asyncio.gather(
            db.transactions.find_many(where={
                "wallet_id":           wallet.wallet_id,
                "transaction_type_id": {"in": credit_ids},
                "transaction_at":      {"gte": start_this, "lt": end_this},
            }),
            db.transactions.find_many(where={
                "wallet_id":           wallet.wallet_id,
                "transaction_type_id": {"in": credit_ids},
                "transaction_at":      {"gte": start_last, "lt": end_last},
            }),
        )
        pts_this = sum(t.amount for t in txns_this)
        pts_last = sum(t.amount for t in txns_last)
    else:
        pts_this = pts_last = 0

    rewards_total, rewards_this, rewards_last = await asyncio.gather(
        db.reward_history.count(where={"wallet_id": wallet.wallet_id}),
        db.reward_history.count(where={"wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start_this, "lt": end_this}}),
        db.reward_history.count(where={"wallet_id": wallet.wallet_id,
            "granted_at": {"gte": start_last, "lt": end_last}}),
    )

    return {
        "available_points":    wallet.available_points,
        "total_earned_points": wallet.total_earned_points,
        "pts_this_month":      pts_this,
        "pts_last_month":      pts_last,
        "rewards_total":       rewards_total,
        "rewards_this_month":  rewards_this,
        "rewards_last_month":  rewards_last,
    }


@router.get("/internal/wallets/stats/batch")
async def get_wallet_stats_batch(employee_ids: str = Query(...)):
    """
    Bulk wallet stats for a comma-separated list of employee_ids.
    Returns a dict keyed by employee_id — missing wallets get zeroed stats.

    Replaces N parallel calls to /internal/wallets/stats on the analytics
    dashboard (one per employee) with a single request + O(1) DB round-trips.

    Called by internal_client.get_wallet_stats_batch().
    """
    ids = [eid.strip() for eid in employee_ids.split(",") if eid.strip()]
    if not ids:
        return {}

    now        = _now()
    start_this, end_this = _month_range(now)
    start_last, end_last = _month_range(now - relativedelta(months=1))

    # ── Fetch all wallets in one query ────────────────────────────────────────
    wallets = await db.wallets.find_many(where={"employee_id": {"in": ids}})
    wallet_map = {w.employee_id: w for w in wallets}
    wallet_ids = [w.wallet_id for w in wallets]

    # ── Zero result template ──────────────────────────────────────────────────
    zero = {
        "available_points": 0, "total_earned_points": 0,
        "pts_this_month": 0,   "pts_last_month": 0,
        "rewards_total": 0,    "rewards_this_month": 0, "rewards_last_month": 0,
    }

    if not wallet_ids:
        return {eid: dict(zero) for eid in ids}

    # ── Fetch credit transaction types (cached implicitly via shared result) ──
    credit_types = await db.transaction_types.find_many(where={"is_credit": True})
    credit_ids   = [t.type_id for t in credit_types]

    # ── Bulk fetch transactions and reward history ────────────────────────────
    if credit_ids:
        txns_this_all, txns_last_all = await asyncio.gather(
            db.transactions.find_many(where={
                "wallet_id":           {"in": wallet_ids},
                "transaction_type_id": {"in": credit_ids},
                "transaction_at":      {"gte": start_this, "lt": end_this},
            }),
            db.transactions.find_many(where={
                "wallet_id":           {"in": wallet_ids},
                "transaction_type_id": {"in": credit_ids},
                "transaction_at":      {"gte": start_last, "lt": end_last},
            }),
        )
    else:
        txns_this_all = txns_last_all = []

    rewards_all, rewards_this_all, rewards_last_all = await asyncio.gather(
        db.reward_history.find_many(where={"wallet_id": {"in": wallet_ids}}),
        db.reward_history.find_many(where={
            "wallet_id":  {"in": wallet_ids},
            "granted_at": {"gte": start_this, "lt": end_this},
        }),
        db.reward_history.find_many(where={
            "wallet_id":  {"in": wallet_ids},
            "granted_at": {"gte": start_last, "lt": end_last},
        }),
    )

    # ── Aggregate per wallet ──────────────────────────────────────────────────
    pts_this_by_wallet:   dict[str, int] = {}
    pts_last_by_wallet:   dict[str, int] = {}
    rewards_by_wallet:    dict[str, int] = {}
    rew_this_by_wallet:   dict[str, int] = {}
    rew_last_by_wallet:   dict[str, int] = {}

    for t in txns_this_all:
        wid = str(t.wallet_id)
        pts_this_by_wallet[wid] = pts_this_by_wallet.get(wid, 0) + t.amount
    for t in txns_last_all:
        wid = str(t.wallet_id)
        pts_last_by_wallet[wid] = pts_last_by_wallet.get(wid, 0) + t.amount
    for r in rewards_all:
        wid = str(r.wallet_id)
        rewards_by_wallet[wid] = rewards_by_wallet.get(wid, 0) + 1
    for r in rewards_this_all:
        wid = str(r.wallet_id)
        rew_this_by_wallet[wid] = rew_this_by_wallet.get(wid, 0) + 1
    for r in rewards_last_all:
        wid = str(r.wallet_id)
        rew_last_by_wallet[wid] = rew_last_by_wallet.get(wid, 0) + 1

    # ── Build response keyed by employee_id ───────────────────────────────────
    result = {}
    for eid in ids:
        wallet = wallet_map.get(eid)
        if not wallet:
            result[eid] = dict(zero)
            continue
        wid = str(wallet.wallet_id)
        result[eid] = {
            "available_points":    wallet.available_points,
            "total_earned_points": wallet.total_earned_points,
            "pts_this_month":      pts_this_by_wallet.get(wid, 0),
            "pts_last_month":      pts_last_by_wallet.get(wid, 0),
            "rewards_total":       rewards_by_wallet.get(wid, 0),
            "rewards_this_month":  rew_this_by_wallet.get(wid, 0),
            "rewards_last_month":  rew_last_by_wallet.get(wid, 0),
        }
    return result

@router.get("/internal/wallets/by-id/{wallet_id}")
async def get_wallet_by_id(wallet_id: str):
    wallet = await db.wallets.find_unique(where={"wallet_id": wallet_id})
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return {
        "wallet_id":        str(wallet.wallet_id),
        "employee_id":      str(wallet.employee_id),
        "available_points": wallet.available_points,
    }

@router.get("/internal/wallets/leaderboard")
async def get_leaderboard(limit: int = Query(10, ge=1, le=50)):
    rows = await db.wallets.find_many(
        order={"total_earned_points": "desc"},
        take=limit,
        include={
            "employees_wallets_employee_idToemployees": {
                "include": {"departments_employees_department_idTodepartments": True}
            }
        },
    )
    result = []
    for rank, w in enumerate(rows, start=1):
        emp  = w.employees_wallets_employee_idToemployees
        dept = emp.departments_employees_department_idTodepartments if emp else None
        result.append({
            "rank":                rank,
            "employee_id":         str(emp.employee_id) if emp else str(w.employee_id),
            "username":            emp.username if emp else "Unknown",
            "department":          dept.department_name if dept else "N/A",
            "total_earned_points": w.total_earned_points,
        })
    return result