"""
src/recognition/internal_router.py
────────────────────────────────────
Internal-only endpoints consumed by the Analytics service.

ROUTING NOTE — same principle as wallet/internal_router.py
───────────────────────────────────────────────────────────
Routes are written as /internal/reviews/... with NO APIRouter prefix.
In recognition/main.py: app.include_router(internal_router)  ← no prefix

The internal_client calls:
    http://localhost:8005/internal/reviews/stats
    http://localhost:8005/internal/reviews/stats/batch   ← NEW
    http://localhost:8005/internal/reviews/recent
    http://localhost:8005/internal/reviews/trend
    http://localhost:8005/internal/reviews/by-user
    http://localhost:8005/internal/reviews/by-team
    http://localhost:8005/internal/reviews/participation
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from src.recognition import service

router = APIRouter(tags=["Internal"])


@router.get("/internal/reviews/stats")
async def review_stats(employee_id: str = Query(...)):
    return await service.get_review_stats_internal(employee_id)


@router.get("/internal/reviews/stats/batch")
async def review_stats_batch(employee_ids: str = Query(...)):
    """
    Bulk review stats for a comma-separated list of employee_ids.
    Returns a dict keyed by employee_id — employees with no reviews get zeroed stats.

    Replaces N parallel calls to /internal/reviews/stats on the analytics
    dashboard teams endpoint with a single request.

    Called by internal_client.get_review_stats_batch().
    """
    ids = [eid.strip() for eid in employee_ids.split(",") if eid.strip()]
    return await service.get_review_stats_batch_internal(ids)


@router.get("/internal/reviews/recent")
async def recent_reviews(
    employee_id: str = Query(...),
    limit: int = Query(5, ge=1, le=20),
):
    return await service.get_recent_reviews_internal(employee_id, limit)


@router.get("/internal/reviews/trend")
async def recognition_trend(
    range: Literal["3m", "6m", "1y"] = Query("6m"),
):
    return await service.get_recognition_trend_internal(range)


@router.get("/internal/reviews/by-user")
async def recognition_by_user(
    range:  Literal["week", "month", "quarter", "year"] = Query("month"),
    page:   int = Query(1,  ge=1),
    limit:  int = Query(20, ge=1, le=100),
):
    return await service.get_recognition_by_user_internal(range, page, limit)


@router.get("/internal/reviews/by-team")
async def recognition_by_team(
    range:  Literal["week", "month", "quarter", "year"] = Query("month"),
    page:   int = Query(1,  ge=1),
    limit:  int = Query(10, ge=1, le=50),
):
    return await service.get_recognition_by_team_internal(range, page, limit)


@router.get("/internal/reviews/participation")
async def participation():
    return await service.get_participation_internal()