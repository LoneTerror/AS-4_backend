"""
tests/test_schemas.py
──────────────────────
Pydantic schema validation — no DB or IO involved.
"""
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.recognition.schemas import (
    PaginatedReviewCategoryResponse,
    PaginatedReviewResponse,
    PaginationMeta,
    ReviewCategoryCreateRequest,
    ReviewCategoryResponse,
    ReviewCategoryTagResponse,
    ReviewCategoryUpdateRequest,
    ReviewCreateRequest,
    ReviewResponse,
    ReviewUpdateRequest,
)

CAT_ID  = uuid.uuid4()
REV_ID  = uuid.uuid4()
EMP_ID  = uuid.uuid4()
EMP2_ID = uuid.uuid4()
STAT_ID = uuid.uuid4()
NOW     = "2026-01-15T10:00:00Z"

# ─────────────────────────────────────────────────────────────────────────────
# ReviewCreateRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCreateRequest:
    def _valid(self, **overrides):
        base = dict(
            receiver_id=EMP_ID,
            comment="This is a valid comment with more than ten chars",
            category_ids=[CAT_ID],
        )
        base.update(overrides)
        return ReviewCreateRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.receiver_id == EMP_ID
        assert len(r.category_ids) == 1

    def test_up_to_five_categories(self):
        cats = [uuid.uuid4() for _ in range(5)]
        r = self._valid(category_ids=cats)
        assert len(r.category_ids) == 5

    def test_too_many_categories_raises(self):
        cats = [uuid.uuid4() for _ in range(6)]
        with pytest.raises(ValidationError):
            self._valid(category_ids=cats)

    def test_empty_categories_raises(self):
        with pytest.raises(ValidationError):
            self._valid(category_ids=[])

    def test_duplicate_category_ids_raises(self):
        same = uuid.uuid4()
        with pytest.raises(ValidationError, match="Duplicate"):
            self._valid(category_ids=[same, same])

    def test_comment_too_short_raises(self):
        with pytest.raises(ValidationError):
            self._valid(comment="short")

    def test_comment_exactly_10_chars_ok(self):
        r = self._valid(comment="1234567890")
        assert r.comment == "1234567890"

    def test_comment_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(comment="x" * 2001)

    def test_comment_max_length_ok(self):
        r = self._valid(comment="x" * 2000)
        assert len(r.comment) == 2000

    def test_optional_image_url(self):
        r = self._valid(image_url="https://cdn.example.com/img.jpg")
        assert str(r.image_url).startswith("https://")

    def test_optional_video_url(self):
        r = self._valid(video_url="https://cdn.example.com/vid.mp4")
        assert str(r.video_url).startswith("https://")

    def test_url_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(image_url="https://example.com/" + "x" * 490)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            self._valid(unknown_field="oops")

    def test_none_urls_accepted(self):
        r = self._valid(image_url=None, video_url=None)
        assert r.image_url is None
        assert r.video_url is None


# ─────────────────────────────────────────────────────────────────────────────
# ReviewUpdateRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewUpdateRequest:
    def test_comment_only(self):
        r = ReviewUpdateRequest(comment="Updated comment is long enough")
        assert r.comment is not None

    def test_category_ids_only(self):
        r = ReviewUpdateRequest(category_ids=[CAT_ID])
        assert len(r.category_ids) == 1

    def test_empty_update_raises(self):
        with pytest.raises(ValidationError, match="At least one field"):
            ReviewUpdateRequest()

    def test_duplicate_category_ids_raises(self):
        same = uuid.uuid4()
        with pytest.raises(ValidationError, match="Duplicate"):
            ReviewUpdateRequest(category_ids=[same, same])

    def test_url_too_long_raises(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(image_url="https://x.com/" + "a" * 490)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(comment="valid comment here", extra="nope")

    def test_all_fields_valid(self):
        r = ReviewUpdateRequest(
            comment="Updated comment for the review",
            category_ids=[CAT_ID, uuid.uuid4()],
            image_url="https://cdn.example.com/img.png",
            video_url="https://cdn.example.com/vid.mp4",
        )
        assert r.comment is not None
        assert len(r.category_ids) == 2


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCategoryCreateRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCategoryCreateRequest:
    def _valid(self, **overrides):
        base = dict(category_code="innovation", category_name="Innovation", multiplier=1.4)
        base.update(overrides)
        return ReviewCategoryCreateRequest(**base)

    def test_code_uppercased(self):
        r = self._valid(category_code="  teamwork  ")
        assert r.category_code == "TEAMWORK"

    def test_name_stripped(self):
        r = self._valid(category_name="  Leadership  ")
        assert r.category_name == "Leadership"

    def test_multiplier_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._valid(multiplier=0.0)

    def test_negative_multiplier_raises(self):
        with pytest.raises(ValidationError):
            self._valid(multiplier=-1.0)

    def test_description_optional(self):
        r = self._valid()
        assert r.description is None

    def test_description_provided(self):
        r = self._valid(description="A description")
        assert r.description == "A description"

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            self._valid(is_active=True)

    def test_description_max_length(self):
        r = self._valid(description="x" * 500)
        assert len(r.description) == 500

    def test_description_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(description="x" * 501)


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCategoryUpdateRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCategoryUpdateRequest:
    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="At least one field"):
            ReviewCategoryUpdateRequest()

    def test_is_active_only(self):
        r = ReviewCategoryUpdateRequest(is_active=False)
        assert r.is_active is False

    def test_code_uppercased(self):
        r = ReviewCategoryUpdateRequest(category_code="ownership")
        assert r.category_code == "OWNERSHIP"

    def test_zero_multiplier_raises(self):
        with pytest.raises(ValidationError):
            ReviewCategoryUpdateRequest(multiplier=0.0)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ReviewCategoryUpdateRequest(multiplier=1.2, unknown="x")


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCategoryResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCategoryResponse:
    def _make(self, **overrides):
        base = dict(
            category_id=CAT_ID, category_code="INNOVATION",
            category_name="Innovation", multiplier=1.4, is_active=True,
        )
        base.update(overrides)
        return ReviewCategoryResponse(**base)

    def test_valid(self):
        r = self._make()
        assert r.category_code == "INNOVATION"
        assert r.multiplier == 1.4

    def test_description_optional(self):
        r = self._make()
        assert r.description is None


# ─────────────────────────────────────────────────────────────────────────────
# ReviewCategoryTagResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewCategoryTagResponse:
    def test_valid(self):
        t = ReviewCategoryTagResponse(
            category_id=CAT_ID, category_code="TEAMWORK", multiplier_snapshot=1.2
        )
        assert t.multiplier_snapshot == 1.2


# ─────────────────────────────────────────────────────────────────────────────
# ReviewResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewResponse:
    def _make(self, **overrides):
        base = dict(
            review_id=REV_ID, reviewer_id=EMP_ID, receiver_id=EMP2_ID,
            comment="Great work!", status_id=STAT_ID,
            review_at=NOW, created_at=NOW, created_by=EMP_ID,
            updated_at=NOW, updated_by=EMP_ID,
        )
        base.update(overrides)
        return ReviewResponse(**base)

    def test_minimal_valid(self):
        r = self._make()
        assert r.comment == "Great work!"

    def test_optional_raw_points(self):
        r = self._make()
        assert r.raw_points is None

    def test_raw_points_provided(self):
        r = self._make(raw_points=2.6)
        assert r.raw_points == 2.6

    def test_category_tags_optional(self):
        r = self._make()
        assert r.category_tags is None

    def test_with_category_tags(self):
        tag = ReviewCategoryTagResponse(
            category_id=CAT_ID, category_code="INNOVATION", multiplier_snapshot=1.4
        )
        r = self._make(category_tags=[tag])
        assert len(r.category_tags) == 1


# ─────────────────────────────────────────────────────────────────────────────
# PaginationMeta
# ─────────────────────────────────────────────────────────────────────────────

class TestPaginationMeta:
    def test_fields(self):
        p = PaginationMeta(
            current_page=1, per_page=20, total=50,
            total_pages=3, has_next=True, has_previous=False,
        )
        assert p.total_pages == 3
        assert p.has_next is True
