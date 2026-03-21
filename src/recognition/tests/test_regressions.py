"""
tests/test_regressions.py
──────────────────────────
Regression tests that guard against known bugs and edge cases discovered
during development.  Each test is named after the issue it prevents.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.recognition.service as svc
from src.recognition.points_engine import calculate_points
from src.recognition.schemas import (
    ReviewCategoryUpdateRequest,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)
from conftest import _fake_category, _fake_review, _fake_tag, make_uuid


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: total_pages must be 0 when total=0 (avoid ZeroDivisionError)
# ─────────────────────────────────────────────────────────────────────────────

class TestPaginationZeroDivision:
    async def test_list_categories_zero_total(self):
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.count    = AsyncMock(return_value=0)
            mock_rc.find_many = AsyncMock(return_value=[])
            result = await svc.list_review_categories(page=1, limit=20)
        assert result["pagination"]["total_pages"] == 0

    async def test_list_reviews_zero_total(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count    = AsyncMock(return_value=0)
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.list_reviews(page=1, limit=20)
        assert result["pagination"]["total_pages"] == 0

    async def test_batch_stats_zero_total_participation(self):
        """get_participation_internal must not divide by zero when no active employees."""
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            result = await svc.get_participation_internal()
        stats = result["stats"]
        assert stats["participation_rate"]         == 0.0
        assert stats["avg_reviews_per_employee"]   == 0.0
        assert stats["avg_reviews_last_month"]     == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: _serialize_review must not raise for None row
# ─────────────────────────────────────────────────────────────────────────────

class TestSerializeNoneRow:
    def test_none_row_returns_empty_dict(self):
        result = svc._serialize_review(None)
        assert result == {}

    def test_review_with_no_tags_attribute(self):
        r = _fake_review()
        r.review_category_tags = None  # simulate missing relation
        # Should fall back to empty list
        result = svc._serialize_review(r)
        assert result["category_tags"] == []


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: points engine formula must be strictly multiplicative
# ─────────────────────────────────────────────────────────────────────────────

class TestPointsFormulaIsMultiplicative:
    def test_two_categories_sum_then_multiply(self):
        """INNOVATION(1.4) + TEAMWORK(1.2) = 2.6 × weight"""
        r = calculate_points(total_category_multiplier=1.4 + 1.2, reviewer_weight=1.0)
        assert r.raw_points == pytest.approx(2.6)

    def test_five_categories_at_max(self):
        total_mult = 1.4 + 1.3 + 1.2 + 1.1 + 1.0  # 6.0
        r = calculate_points(total_category_multiplier=total_mult, reviewer_weight=2.0)
        assert r.raw_points == pytest.approx(12.0)

    def test_single_category_identity(self):
        r = calculate_points(total_category_multiplier=1.0, reviewer_weight=1.0)
        assert r.raw_points == pytest.approx(1.0)

    def test_reviewer_weight_scales_linearly(self):
        r1 = calculate_points(total_category_multiplier=2.0, reviewer_weight=1.0)
        r2 = calculate_points(total_category_multiplier=2.0, reviewer_weight=2.0)
        assert r2.raw_points == pytest.approx(r1.raw_points * 2)


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: category multiplier frozen at write time (snapshot integrity)
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiplierSnapshotIntegrity:
    def test_tag_snapshot_differs_from_current_category_multiplier(self):
        """Even if the category multiplier changes, the tag snapshot stays frozen."""
        tag = _fake_tag(multiplier_snapshot=1.4)
        # Simulate: category now has multiplier=2.0 but old reviews still show 1.4
        r   = _fake_review(tags=[tag])
        result = svc._serialize_review(r)
        assert result["category_tags"][0]["multiplier_snapshot"] == 1.4

    def test_multiple_tag_snapshots_serialised_independently(self):
        tag1 = _fake_tag(code_snapshot="INNOVATION", multiplier_snapshot=1.4)
        tag2 = _fake_tag(code_snapshot="TEAMWORK",   multiplier_snapshot=1.2)
        r    = _fake_review(tags=[tag1, tag2])
        result = svc._serialize_review(r)
        snapshots = {t["category_code"]: t["multiplier_snapshot"] for t in result["category_tags"]}
        assert snapshots["INNOVATION"] == 1.4
        assert snapshots["TEAMWORK"]   == 1.2


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: schema validators fire correctly
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaValidationRegressions:
    def test_category_code_normalised_to_uppercase(self):
        from src.recognition.schemas import ReviewCategoryCreateRequest
        r = ReviewCategoryCreateRequest(category_code="innovation", category_name="Innovation", multiplier=1.4)
        assert r.category_code == "INNOVATION"

    def test_category_name_stripped(self):
        from src.recognition.schemas import ReviewCategoryCreateRequest
        r = ReviewCategoryCreateRequest(category_code="X", category_name="  Spaces  ", multiplier=1.0)
        assert r.category_name == "Spaces"

    def test_duplicate_category_ids_rejected_on_create(self):
        from pydantic import ValidationError
        same = uuid.uuid4()
        with pytest.raises(ValidationError, match="Duplicate"):
            ReviewCreateRequest(
                receiver_id=uuid.uuid4(),
                comment="Valid comment that is long enough",
                category_ids=[same, same],
            )

    def test_duplicate_category_ids_rejected_on_update(self):
        from pydantic import ValidationError
        same = uuid.uuid4()
        with pytest.raises(ValidationError, match="Duplicate"):
            ReviewUpdateRequest(category_ids=[same, same])

    def test_empty_update_request_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="At least one field"):
            ReviewUpdateRequest()

    def test_empty_category_update_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="At least one field"):
            ReviewCategoryUpdateRequest()

    def test_review_comment_min_length_boundary(self):
        from pydantic import ValidationError
        # 9 chars: too short
        with pytest.raises(ValidationError):
            ReviewCreateRequest(
                receiver_id=uuid.uuid4(),
                comment="123456789",
                category_ids=[uuid.uuid4()],
            )
        # 10 chars: OK
        r = ReviewCreateRequest(
            receiver_id=uuid.uuid4(),
            comment="1234567890",
            category_ids=[uuid.uuid4()],
        )
        assert len(r.comment) == 10


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: batch stats returns zeros for employees with no reviews
# ─────────────────────────────────────────────────────────────────────────────

class TestBatchStatsZeroFill:
    async def test_employees_with_no_reviews_get_zeroed_stats(self):
        eid1, eid2 = make_uuid(), make_uuid()
        # Only eid1 has a review
        review = _fake_review(receiver_id=eid1)
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(side_effect=[[review], [review], []])
            result = await svc.get_review_stats_batch_internal([eid1, eid2])
        assert result[eid2]["reviews_total"]      == 0
        assert result[eid2]["reviews_this_month"] == 0
        assert result[eid2]["reviews_last_month"] == 0

    async def test_all_three_keys_always_present(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_review_stats_batch_internal([eid])
        assert "reviews_total"      in result[eid]
        assert "reviews_this_month" in result[eid]
        assert "reviews_last_month" in result[eid]


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: reviewer_weight falls back to 1.0 on DB error
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewerWeightFallback:
    async def test_db_error_during_weight_lookup_defaults_to_one(self):
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(side_effect=Exception("Timeout"))
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.0

    async def test_role_without_reviewer_weight_attribute_uses_default(self):
        role = MagicMock(spec=[])  # no reviewer_weight attribute
        er   = MagicMock(); er.roles = role
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(return_value=[er])
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.0

    async def test_none_reviewer_weight_skipped(self):
        role = MagicMock(); role.reviewer_weight = None
        er   = MagicMock(); er.roles = role
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(return_value=[er])
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: list_reviews with no filter must NOT pass where= to Prisma
# (Prisma 0.15.0 bug with empty where dict)
# ─────────────────────────────────────────────────────────────────────────────

class TestListReviewsNoPrismaWhereBug:
    async def test_no_filter_calls_find_many_without_where(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count    = AsyncMock(return_value=0)
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.list_reviews()
        call_kwargs = mock_r.find_many.call_args.kwargs
        assert "where" not in call_kwargs, (
            "Prisma bug: passing where={} can corrupt queries on 0.15.0"
        )

    async def test_with_reviewer_id_does_pass_where(self):
        rid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count    = AsyncMock(return_value=0)
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.list_reviews(reviewer_id=rid)
        call_kwargs = mock_r.find_many.call_args.kwargs
        assert "where" in call_kwargs
        assert call_kwargs["where"]["reviewer_id"] == rid


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: create_review raises 400 not 500 for inactive category
# ─────────────────────────────────────────────────────────────────────────────

class TestInactiveCategoryRaisesCorrectCode:
    async def test_inactive_category_gives_400(self):
        body = ReviewCreateRequest(
            receiver_id=uuid.uuid4(),
            comment="Valid comment for the review record",
            category_ids=[uuid.uuid4()],
        )
        with patch.object(svc.db, "review_categories") as mock_cats:
            # find_many returns empty list (category is inactive / not found)
            mock_cats.find_many = AsyncMock(return_value=[])
            with pytest.raises(HTTPException) as exc:
                await svc.create_review(body, make_uuid())
        assert exc.value.status_code == 400
        assert "invalid or inactive" in exc.value.detail.lower()
