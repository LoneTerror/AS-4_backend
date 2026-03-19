"""
tests/test_service.py
──────────────────────
Unit tests for src/recognition/service.py.

All Prisma DB calls are patched via unittest.mock.patch so tests run without
a real database.  Each test class covers one service function.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

# ── module under test ────────────────────────────────────────────────────────
import src.recognition.service as svc

# ── helpers from conftest ────────────────────────────────────────────────────
from conftest import _fake_category, _fake_review, _fake_tag, make_uuid


# ─────────────────────────────────────────────────────────────────────────────
# list_review_categories
# ─────────────────────────────────────────────────────────────────────────────

class TestListReviewCategories:
    @pytest.fixture(autouse=True)
    def _patch_db(self):
        self.cat1 = _fake_category(code="INNOVATION")
        self.cat2 = _fake_category(code="TEAMWORK")
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.count  = AsyncMock(return_value=2)
            mock_rc.find_many = AsyncMock(return_value=[self.cat1, self.cat2])
            self.mock_rc = mock_rc
            yield

    async def test_returns_paginated_structure(self):
        result = await svc.list_review_categories(page=1, limit=20)
        assert "data" in result
        assert "pagination" in result

    async def test_data_contains_categories(self):
        result = await svc.list_review_categories(page=1, limit=20)
        assert len(result["data"]) == 2

    async def test_active_only_adds_where_clause(self):
        result = await svc.list_review_categories(page=1, limit=20, active_only=True)
        # count called with where={"is_active": True}
        self.mock_rc.count.assert_awaited_once_with(where={"is_active": True})

    async def test_pagination_meta_correct(self):
        result = await svc.list_review_categories(page=1, limit=20)
        pg = result["pagination"]
        assert pg["current_page"] == 1
        assert pg["total"] == 2
        assert pg["has_next"] is False
        assert pg["has_previous"] is False

    async def test_total_pages_ceil(self):
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.count    = AsyncMock(return_value=25)
            mock_rc.find_many = AsyncMock(return_value=[self.cat1])
            result = await svc.list_review_categories(page=1, limit=20)
        assert result["pagination"]["total_pages"] == 2

    async def test_empty_result(self):
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.count    = AsyncMock(return_value=0)
            mock_rc.find_many = AsyncMock(return_value=[])
            result = await svc.list_review_categories()
        assert result["pagination"]["total_pages"] == 0

    async def test_page_skip_offset(self):
        await svc.list_review_categories(page=3, limit=10)
        call_kwargs = self.mock_rc.find_many.call_args
        assert call_kwargs.kwargs.get("skip") == 20  # (3-1)*10


# ─────────────────────────────────────────────────────────────────────────────
# create_review_category
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateReviewCategory:
    def _body(self, **overrides):
        from src.recognition.schemas import ReviewCategoryCreateRequest
        base = dict(category_code="LEADERSHIP", category_name="Leadership", multiplier=1.3)
        base.update(overrides)
        return ReviewCategoryCreateRequest(**base)

    async def test_creates_when_no_duplicate(self):
        body    = self._body()
        created = _fake_category(code="LEADERSHIP", name="Leadership")
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_first = AsyncMock(return_value=None)
            mock_rc.create     = AsyncMock(return_value=created)
            result = await svc.create_review_category(body, make_uuid())
        assert result is created

    async def test_raises_409_on_duplicate(self):
        body = self._body()
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_first = AsyncMock(return_value=_fake_category())
            with pytest.raises(HTTPException) as exc:
                await svc.create_review_category(body, make_uuid())
        assert exc.value.status_code == 409

    async def test_create_called_with_correct_data(self):
        body       = self._body()
        user_id    = make_uuid()
        created_ok = _fake_category()
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_first = AsyncMock(return_value=None)
            mock_rc.create     = AsyncMock(return_value=created_ok)
            await svc.create_review_category(body, user_id)
        create_data = mock_rc.create.call_args.kwargs["data"]
        assert create_data["category_code"] == "LEADERSHIP"
        assert create_data["multiplier"]    == 1.3
        assert create_data["created_by"]    == user_id

    async def test_is_active_defaults_to_true(self):
        body    = self._body()
        created = _fake_category()
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_first = AsyncMock(return_value=None)
            mock_rc.create     = AsyncMock(return_value=created)
            await svc.create_review_category(body, make_uuid())
        assert mock_rc.create.call_args.kwargs["data"]["is_active"] is True


# ─────────────────────────────────────────────────────────────────────────────
# update_review_category
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateReviewCategory:
    def _body(self, **kwargs):
        from src.recognition.schemas import ReviewCategoryUpdateRequest
        return ReviewCategoryUpdateRequest(**kwargs)

    async def test_raises_404_when_not_found(self):
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.update_review_category(make_uuid(), self._body(multiplier=1.5), make_uuid())
        assert exc.value.status_code == 404

    async def test_updates_when_found(self):
        cat     = _fake_category()
        updated = _fake_category(multiplier=1.9)
        body    = self._body(multiplier=1.9)
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_unique = AsyncMock(return_value=cat)
            mock_rc.update      = AsyncMock(return_value=updated)
            result = await svc.update_review_category(str(cat.category_id), body, make_uuid())
        assert result is updated

    async def test_only_provided_fields_included(self):
        cat  = _fake_category()
        body = self._body(is_active=False)
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_unique = AsyncMock(return_value=cat)
            mock_rc.update      = AsyncMock(return_value=cat)
            await svc.update_review_category(str(cat.category_id), body, make_uuid())
        update_data = mock_rc.update.call_args.kwargs["data"]
        assert "is_active" in update_data
        assert "multiplier" not in update_data

    async def test_updated_by_set_to_user(self):
        cat     = _fake_category()
        user_id = make_uuid()
        body    = self._body(multiplier=1.1)
        with patch.object(svc.db, "review_categories") as mock_rc:
            mock_rc.find_unique = AsyncMock(return_value=cat)
            mock_rc.update      = AsyncMock(return_value=cat)
            await svc.update_review_category(str(cat.category_id), body, user_id)
        assert mock_rc.update.call_args.kwargs["data"]["updated_by"] == user_id


# ─────────────────────────────────────────────────────────────────────────────
# list_reviews
# ─────────────────────────────────────────────────────────────────────────────

class TestListReviews:
    def _make_reviews(self, n=3):
        return [_fake_review() for _ in range(n)]

    @pytest.fixture(autouse=True)
    def _patch_db(self):
        with patch.object(svc.db, "reviews") as mock_r:
            self.mock_r = mock_r
            yield

    async def test_returns_paginated_structure(self):
        reviews = self._make_reviews(2)
        self.mock_r.count    = AsyncMock(return_value=2)
        self.mock_r.find_many = AsyncMock(return_value=reviews)
        result = await svc.list_reviews(page=1, limit=20)
        assert "data" in result
        assert "pagination" in result

    async def test_serialises_reviews(self):
        r = _fake_review()
        self.mock_r.count    = AsyncMock(return_value=1)
        self.mock_r.find_many = AsyncMock(return_value=[r])
        result = await svc.list_reviews()
        assert result["data"][0]["review_id"] == r.review_id

    async def test_reviewer_id_filter_applied(self):
        reviewer_id = make_uuid()
        self.mock_r.count    = AsyncMock(return_value=0)
        self.mock_r.find_many = AsyncMock(return_value=[])
        await svc.list_reviews(reviewer_id=reviewer_id)
        # when reviewer_id is set, find_many receives a where kwarg
        call_kwargs = self.mock_r.find_many.call_args.kwargs
        assert call_kwargs.get("where", {}).get("reviewer_id") == reviewer_id

    async def test_receiver_id_filter_applied(self):
        receiver_id = make_uuid()
        self.mock_r.count    = AsyncMock(return_value=0)
        self.mock_r.find_many = AsyncMock(return_value=[])
        await svc.list_reviews(receiver_id=receiver_id)
        call_kwargs = self.mock_r.find_many.call_args.kwargs
        assert call_kwargs.get("where", {}).get("receiver_id") == receiver_id

    async def test_no_filter_calls_without_where(self):
        self.mock_r.count    = AsyncMock(return_value=0)
        self.mock_r.find_many = AsyncMock(return_value=[])
        await svc.list_reviews()
        # no where kwarg when no filter
        call_kwargs = self.mock_r.find_many.call_args.kwargs
        assert "where" not in call_kwargs

    async def test_pagination_has_next(self):
        reviews = self._make_reviews(20)
        self.mock_r.count    = AsyncMock(return_value=25)
        self.mock_r.find_many = AsyncMock(return_value=reviews)
        result = await svc.list_reviews(page=1, limit=20)
        assert result["pagination"]["has_next"] is True

    async def test_pagination_has_previous(self):
        reviews = self._make_reviews(5)
        self.mock_r.count    = AsyncMock(return_value=25)
        self.mock_r.find_many = AsyncMock(return_value=reviews)
        result = await svc.list_reviews(page=2, limit=20)
        assert result["pagination"]["has_previous"] is True


# ─────────────────────────────────────────────────────────────────────────────
# get_review
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReview:
    async def test_returns_serialised_review(self):
        r = _fake_review()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=r)
            result = await svc.get_review(str(r.review_id))
        assert result["review_id"] == r.review_id

    async def test_raises_404_when_not_found(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.get_review(make_uuid())
        assert exc.value.status_code == 404

    async def test_includes_category_tags_in_result(self):
        tag = _fake_tag(code_snapshot="TEAMWORK", multiplier_snapshot=1.2)
        r   = _fake_review(tags=[tag])
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=r)
            result = await svc.get_review(str(r.review_id))
        assert len(result["category_tags"]) == 1
        assert result["category_tags"][0]["category_code"] == "TEAMWORK"


# ─────────────────────────────────────────────────────────────────────────────
# create_review
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateReview:
    def _body(self, category_ids=None, **overrides):
        from src.recognition.schemas import ReviewCreateRequest
        cat_id = uuid.uuid4()
        base = dict(
            receiver_id=uuid.uuid4(),
            comment="Excellent work on the project end-to-end",
            category_ids=category_ids or [cat_id],
        )
        base.update(overrides)
        return ReviewCreateRequest(**base)

    def _setup_mocks(self, mock_cats, mock_reviews, mock_status, cat_multiplier=1.4):
        cat = _fake_category(multiplier=cat_multiplier)
        cat.category_id   = str(uuid.uuid4())
        cat.category_code = "INNOVATION"
        cat.multiplier    = cat_multiplier

        mock_cats.find_many   = AsyncMock(return_value=[cat])
        mock_reviews.count    = AsyncMock(return_value=0)
        mock_reviews.find_many = AsyncMock(return_value=[])
        mock_reviews.create   = AsyncMock(return_value=_fake_review(raw_points=cat_multiplier))
        mock_reviews.create_many = AsyncMock(return_value=MagicMock(count=1))

        sm = MagicMock()
        sm.status_id = make_uuid()
        mock_status.find_first = AsyncMock(return_value=sm)

        return cat

    async def test_raises_400_for_invalid_category(self):
        body = self._body()
        with patch.object(svc.db, "review_categories") as mock_cats:
            mock_cats.find_many = AsyncMock(return_value=[])  # none found
            with pytest.raises(HTTPException) as exc:
                await svc.create_review(body, make_uuid())
        assert exc.value.status_code == 400

    async def test_raises_500_when_no_active_status(self):
        body = self._body()
        with (
            patch.object(svc.db, "review_categories") as mock_cats,
            patch.object(svc.db, "employee_roles") as mock_er,
            patch.object(svc.db, "status_master") as mock_sm,
        ):
            mock_cats.find_many = AsyncMock(return_value=[_fake_category()])
            mock_er.find_many   = AsyncMock(return_value=[])
            mock_sm.find_first  = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.create_review(body, make_uuid())
        assert exc.value.status_code == 500

    async def test_creates_review_successfully(self):
        body        = self._body()
        reviewer_id = make_uuid()
        with (
            patch.object(svc.db, "review_categories")    as mock_cats,
            patch.object(svc.db, "employee_roles")       as mock_er,
            patch.object(svc.db, "status_master")        as mock_sm,
            patch.object(svc.db, "reviews")              as mock_r,
            patch.object(svc.db, "review_category_tags") as mock_tags,
            patch("src.recognition.service.publish", new_callable=AsyncMock),
        ):
            self._setup_mocks(mock_cats, mock_r, mock_sm)
            mock_er.find_many  = AsyncMock(return_value=[])
            mock_tags.create   = AsyncMock(return_value=MagicMock())   # per-tag loop
            serialised_row     = _fake_review()
            mock_r.find_unique = AsyncMock(return_value=serialised_row)
            result = await svc.create_review(body, reviewer_id)
        assert "review_id" in result

    async def test_uses_default_reviewer_weight_when_no_role(self):
        body        = self._body()
        reviewer_id = make_uuid()
        with (
            patch.object(svc.db, "review_categories")    as mock_cats,
            patch.object(svc.db, "employee_roles")       as mock_er,
            patch.object(svc.db, "status_master")        as mock_sm,
            patch.object(svc.db, "reviews")              as mock_r,
            patch.object(svc.db, "review_category_tags") as mock_tags,
            patch("src.recognition.service.publish", new_callable=AsyncMock) as mock_pub,
        ):
            self._setup_mocks(mock_cats, mock_r, mock_sm)
            mock_er.find_many  = AsyncMock(return_value=[])
            mock_tags.create   = AsyncMock(return_value=MagicMock())
            mock_r.find_unique = AsyncMock(return_value=_fake_review(raw_points=1.4))
            await svc.create_review(body, reviewer_id)
            mock_pub.assert_awaited_once()

    async def test_publishes_event_after_create(self):
        body = self._body()
        with (
            patch.object(svc.db, "review_categories")    as mock_cats,
            patch.object(svc.db, "employee_roles")       as mock_er,
            patch.object(svc.db, "status_master")        as mock_sm,
            patch.object(svc.db, "reviews")              as mock_r,
            patch.object(svc.db, "review_category_tags") as mock_tags,
            patch("src.recognition.service.publish", new_callable=AsyncMock) as mock_pub,
        ):
            self._setup_mocks(mock_cats, mock_r, mock_sm)
            mock_er.find_many  = AsyncMock(return_value=[])
            mock_tags.create   = AsyncMock(return_value=MagicMock())
            mock_r.find_unique = AsyncMock(return_value=_fake_review())
            await svc.create_review(body, make_uuid())
            assert mock_pub.await_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# _serialize_review  (private helper)
# ─────────────────────────────────────────────────────────────────────────────

class TestSerializeReview:
    def test_none_returns_empty_dict(self):
        assert svc._serialize_review(None) == {}

    def test_basic_fields_present(self):
        r      = _fake_review()
        result = svc._serialize_review(r)
        for key in ("review_id", "reviewer_id", "receiver_id", "comment",
                    "status_id", "review_at", "raw_points"):
            assert key in result

    def test_tags_serialised(self):
        tag    = _fake_tag(code_snapshot="OWNERSHIP", multiplier_snapshot=1.1)
        r      = _fake_review(tags=[tag])
        result = svc._serialize_review(r)
        assert result["category_codes"] == ["OWNERSHIP"]
        assert result["category_ids"]   == [tag.category_id]
        assert result["category_tags"][0]["multiplier_snapshot"] == 1.1

    def test_empty_tags_yields_empty_lists(self):
        r      = _fake_review(tags=[])
        result = svc._serialize_review(r)
        assert result["category_tags"]  == []
        assert result["category_ids"]   == []
        assert result["category_codes"] == []


# ─────────────────────────────────────────────────────────────────────────────
# _get_reviewer_weight  (private helper)
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReviewerWeight:
    async def test_returns_weight_from_role(self):
        role = MagicMock()
        role.reviewer_weight = 1.5
        emp_role = MagicMock()
        emp_role.roles = role
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(return_value=[emp_role])
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.5

    async def test_defaults_to_1_when_no_role(self):
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(return_value=[])
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.0

    async def test_defaults_to_1_on_exception(self):
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(side_effect=Exception("DB down"))
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.0

    async def test_returns_first_valid_weight(self):
        role1 = MagicMock(); role1.reviewer_weight = 1.2
        role2 = MagicMock(); role2.reviewer_weight = 1.8
        er1 = MagicMock(); er1.roles = role1
        er2 = MagicMock(); er2.roles = role2
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_many = AsyncMock(return_value=[er1, er2])
            weight = await svc._get_reviewer_weight(make_uuid())
        assert weight == 1.2  # first one wins


# ─────────────────────────────────────────────────────────────────────────────
# get_review_stats_batch_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReviewStatsBatchInternal:
    async def test_empty_list_returns_empty_dict(self):
        result = await svc.get_review_stats_batch_internal([])
        assert result == {}

    async def test_returns_keyed_by_employee_id(self):
        eid = make_uuid()
        r   = _fake_review(receiver_id=eid)
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[r])
            result = await svc.get_review_stats_batch_internal([eid])
        assert eid in result

    async def test_all_stats_keys_present(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_review_stats_batch_internal([eid])
        assert set(result[eid].keys()) == {"reviews_total", "reviews_this_month", "reviews_last_month"}

    async def test_employees_without_reviews_get_zeros(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_review_stats_batch_internal([eid])
        assert result[eid]["reviews_total"] == 0

    async def test_counts_correctly_across_buckets(self):
        eid   = make_uuid()
        row   = _fake_review(receiver_id=eid)
        with patch.object(svc.db, "reviews") as mock_r:
            # all_reviews=1, this_month=1, last_month=0
            mock_r.find_many = AsyncMock(side_effect=[[row], [row], []])
            result = await svc.get_review_stats_batch_internal([eid])
        assert result[eid]["reviews_total"]      == 1
        assert result[eid]["reviews_this_month"] == 1
        assert result[eid]["reviews_last_month"] == 0

    async def test_multiple_employees(self):
        eid1, eid2 = make_uuid(), make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_review_stats_batch_internal([eid1, eid2])
        assert eid1 in result and eid2 in result
