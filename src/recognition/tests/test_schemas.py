"""
test_schemas.py
Unit tests for src/recognition/schemas.py

Covers:
- ReviewCreateRequest: field validation, URL length, extra field rejection
- ReviewUpdateRequest: optional fields, at-least-one guard, URL length
- ReviewResponse: from_attributes, field presence
- PaginationMeta: field types
- PaginatedReviewResponse: nested structure
"""

import os
import sys
import pytest
from uuid import UUID, uuid4
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from pydantic import ValidationError

# Import the REAL schemas module
import importlib.util, pathlib

_schema_path = pathlib.Path(__file__).parent.parent / "schemas.py"
_spec = importlib.util.spec_from_file_location("schemas_module", _schema_path)
_schemas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_schemas)

ReviewCreateRequest    = _schemas.ReviewCreateRequest
ReviewUpdateRequest    = _schemas.ReviewUpdateRequest
ReviewResponse         = _schemas.ReviewResponse
PaginationMeta         = _schemas.PaginationMeta
PaginatedReviewResponse = _schemas.PaginatedReviewResponse

# ---------------------------------------------------------------------------
# Shared sample data
# ---------------------------------------------------------------------------

VALID_UUID   = str(uuid4())
NOW          = datetime.now(timezone.utc)
SHORT_URL    = "https://cdn.example.com/file.jpg"
LONG_URL     = "https://cdn.example.com/" + "x" * 490  # > 500 chars total


def valid_create_payload(**overrides):
    base = dict(
        receiver_id=VALID_UUID,
        rating=4,
        comment="Great performance across all metrics.",
        image_url=None,
        video_url=None,
    )
    base.update(overrides)
    return base


def valid_response_payload(**overrides):
    base = dict(
        review_id=uuid4(),
        reviewer_id=uuid4(),
        receiver_id=uuid4(),
        rating=4,
        comment="Good work",
        image_url=None,
        video_url=None,
        status_id=uuid4(),
        review_at=NOW,
        created_at=NOW,
        created_by=uuid4(),
        updated_at=NOW,
        updated_by=uuid4(),
    )
    base.update(overrides)
    return base


# ===========================================================================
# ReviewCreateRequest
# ===========================================================================

class TestReviewCreateRequest:

    def test_valid_payload_accepted(self):
        req = ReviewCreateRequest(**valid_create_payload())
        assert req.rating == 4

    def test_receiver_id_must_be_valid_uuid(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(receiver_id="not-a-uuid"))

    def test_rating_minimum_is_1(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(rating=0))

    def test_rating_maximum_is_5(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(rating=6))

    def test_rating_exactly_1_is_valid(self):
        req = ReviewCreateRequest(**valid_create_payload(rating=1))
        assert req.rating == 1

    def test_rating_exactly_5_is_valid(self):
        req = ReviewCreateRequest(**valid_create_payload(rating=5))
        assert req.rating == 5

    def test_comment_minimum_length_10(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(comment="Short"))

    def test_comment_maximum_length_2000(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(comment="x" * 2001))

    def test_comment_exactly_10_chars_is_valid(self):
        req = ReviewCreateRequest(**valid_create_payload(comment="1234567890"))
        assert len(req.comment) == 10

    def test_comment_exactly_2000_chars_is_valid(self):
        req = ReviewCreateRequest(**valid_create_payload(comment="x" * 2000))
        assert len(req.comment) == 2000

    def test_image_url_none_is_accepted(self):
        req = ReviewCreateRequest(**valid_create_payload(image_url=None))
        assert req.image_url is None

    def test_valid_https_image_url_accepted(self):
        req = ReviewCreateRequest(**valid_create_payload(image_url=SHORT_URL))
        assert req.image_url is not None

    def test_image_url_exceeding_500_chars_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(image_url=LONG_URL))

    def test_video_url_none_is_accepted(self):
        req = ReviewCreateRequest(**valid_create_payload(video_url=None))
        assert req.video_url is None

    def test_valid_https_video_url_accepted(self):
        req = ReviewCreateRequest(**valid_create_payload(video_url=SHORT_URL))
        assert req.video_url is not None

    def test_video_url_exceeding_500_chars_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(video_url=LONG_URL))

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(unexpected_field="boom"))

    def test_receiver_id_is_stored_as_uuid(self):
        req = ReviewCreateRequest(**valid_create_payload(receiver_id=VALID_UUID))
        assert isinstance(req.receiver_id, UUID)

    def test_all_required_fields_missing_raises(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest()

    def test_rating_float_is_rejected(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(rating=3.5))

    def test_comment_cannot_be_none(self):
        with pytest.raises(ValidationError):
            ReviewCreateRequest(**valid_create_payload(comment=None))


# ===========================================================================
# ReviewUpdateRequest
# ===========================================================================

class TestReviewUpdateRequest:

    def test_only_rating_is_valid(self):
        req = ReviewUpdateRequest(rating=3)
        assert req.rating == 3

    def test_only_comment_is_valid(self):
        req = ReviewUpdateRequest(comment="An updated comment for the review.")
        assert req.comment == "An updated comment for the review."

    def test_all_fields_at_once_is_valid(self):
        req = ReviewUpdateRequest(rating=5, comment="Updated rating and comment.",
                                  image_url=SHORT_URL, video_url=SHORT_URL)
        assert req.rating == 5

    def test_empty_request_raises_at_least_one_field(self):
        with pytest.raises(ValidationError) as exc_info:
            ReviewUpdateRequest()
        assert "At least one field" in str(exc_info.value)

    def test_rating_below_1_rejected(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(rating=0)

    def test_rating_above_5_rejected(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(rating=6)

    def test_comment_too_short_rejected(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(comment="Hi")

    def test_comment_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(comment="y" * 2001)

    def test_image_url_too_long_raises(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(image_url=LONG_URL)

    def test_video_url_too_long_raises(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(video_url=LONG_URL)

    def test_extra_fields_forbidden(self):
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(rating=3, unknown_field="x")

    def test_all_fields_none_explicit_raises(self):
        """Passing all fields as None should still fail the model_validator"""
        with pytest.raises(ValidationError):
            ReviewUpdateRequest(rating=None, comment=None,
                                image_url=None, video_url=None)

    def test_only_image_url_is_valid(self):
        req = ReviewUpdateRequest(image_url=SHORT_URL)
        assert req.image_url is not None

    def test_only_video_url_is_valid(self):
        req = ReviewUpdateRequest(video_url=SHORT_URL)
        assert req.video_url is not None


# ===========================================================================
# ReviewResponse
# ===========================================================================

class TestReviewResponse:

    def test_valid_response_constructed(self):
        resp = ReviewResponse(**valid_response_payload())
        assert isinstance(resp.review_id, UUID)

    def test_optional_image_url_can_be_none(self):
        resp = ReviewResponse(**valid_response_payload(image_url=None))
        assert resp.image_url is None

    def test_optional_video_url_can_be_none(self):
        resp = ReviewResponse(**valid_response_payload(video_url=None))
        assert resp.video_url is None

    def test_image_url_as_string_accepted(self):
        resp = ReviewResponse(**valid_response_payload(image_url=SHORT_URL))
        assert resp.image_url == SHORT_URL

    def test_all_uuid_fields_are_uuid_type(self):
        resp = ReviewResponse(**valid_response_payload())
        for field in ("review_id", "reviewer_id", "receiver_id",
                      "status_id", "created_by", "updated_by"):
            assert isinstance(getattr(resp, field), UUID), f"{field} should be UUID"

    def test_timestamps_are_datetime(self):
        resp = ReviewResponse(**valid_response_payload())
        for field in ("review_at", "created_at", "updated_at"):
            assert isinstance(getattr(resp, field), datetime), f"{field} should be datetime"

    def test_rating_preserved(self):
        resp = ReviewResponse(**valid_response_payload(rating=2))
        assert resp.rating == 2

    def test_comment_preserved(self):
        resp = ReviewResponse(**valid_response_payload(comment="Specific comment text"))
        assert resp.comment == "Specific comment text"

    def test_from_attributes_enabled(self):
        assert ReviewResponse.model_config.get("from_attributes") is True


# ===========================================================================
# PaginationMeta
# ===========================================================================

class TestPaginationMeta:

    def _make(self, **kw):
        defaults = dict(current_page=1, per_page=20, total=100,
                        total_pages=5, has_next=True, has_previous=False)
        defaults.update(kw)
        return PaginationMeta(**defaults)

    def test_valid_pagination_meta(self):
        meta = self._make()
        assert meta.total == 100

    def test_has_next_is_bool(self):
        meta = self._make(has_next=False)
        assert meta.has_next is False

    def test_has_previous_is_bool(self):
        meta = self._make(has_previous=True)
        assert meta.has_previous is True

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            PaginationMeta(current_page=1, per_page=20)  # missing total etc.


# ===========================================================================
# PaginatedReviewResponse
# ===========================================================================

class TestPaginatedReviewResponse:

    def _make_meta(self):
        return dict(current_page=1, per_page=20, total=1,
                    total_pages=1, has_next=False, has_previous=False)

    def test_empty_data_list_valid(self):
        resp = PaginatedReviewResponse(data=[], pagination=self._make_meta())
        assert resp.data == []

    def test_data_list_contains_review_responses(self):
        review = ReviewResponse(**valid_response_payload())
        resp   = PaginatedReviewResponse(data=[review], pagination=self._make_meta())
        assert len(resp.data) == 1
        assert isinstance(resp.data[0], ReviewResponse)

    def test_pagination_field_is_pagination_meta(self):
        resp = PaginatedReviewResponse(data=[], pagination=self._make_meta())
        assert isinstance(resp.pagination, PaginationMeta)

    def test_missing_data_field_raises(self):
        with pytest.raises(ValidationError):
            PaginatedReviewResponse(pagination=self._make_meta())

    def test_missing_pagination_field_raises(self):
        with pytest.raises(ValidationError):
            PaginatedReviewResponse(data=[])
