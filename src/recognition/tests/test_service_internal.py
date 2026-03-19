"""
tests/test_service_internal.py
───────────────────────────────
Tests for the internal analytics service functions and update_review.
These cover the lines not reached by test_service.py.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi import HTTPException

import src.recognition.service as svc
from src.recognition.schemas import ReviewUpdateRequest
from conftest import _fake_category, _fake_review, _fake_tag, make_uuid, utcnow


# ─────────────────────────────────────────────────────────────────────────────
# update_review
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateReview:
    def _body(self, **kwargs):
        return ReviewUpdateRequest(**kwargs)

    async def test_raises_404_when_review_not_found(self):
        body = self._body(comment="Updated comment that is long enough")
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.update_review(make_uuid(), body, make_uuid())
        assert exc.value.status_code == 404

    async def test_raises_403_when_not_reviewer(self):
        owner_id = make_uuid()
        caller_id = make_uuid()
        existing = _fake_review(reviewer_id=owner_id)
        body = self._body(comment="Updated comment that is long enough")
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(return_value=existing)
            with pytest.raises(HTTPException) as exc:
                await svc.update_review(str(existing.review_id), body, caller_id)
        assert exc.value.status_code == 403

    async def test_updates_comment_only(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        updated = _fake_review(reviewer_id=reviewer_id)
        body = self._body(comment="This is my updated review comment")
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(side_effect=[existing, updated])
            mock_r.update = AsyncMock(return_value=updated)
            result = await svc.update_review(str(existing.review_id), body, reviewer_id)
        assert result is not None
        update_data = mock_r.update.call_args.kwargs["data"]
        assert update_data["comment"] == "This is my updated review comment"

    async def test_updates_image_and_video_url(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        updated = _fake_review(reviewer_id=reviewer_id)
        body = self._body(
            image_url="https://example.com/img.jpg",
            video_url="https://example.com/vid.mp4",
        )
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(side_effect=[existing, updated])
            mock_r.update = AsyncMock(return_value=updated)
            await svc.update_review(str(existing.review_id), body, reviewer_id)
        update_data = mock_r.update.call_args.kwargs["data"]
        assert "image_url" in update_data
        assert "video_url" in update_data

    async def test_recalculates_points_when_categories_updated(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        updated = _fake_review(reviewer_id=reviewer_id)
        cat = _fake_category(multiplier=1.4)
        cat_id = uuid.uuid4()
        body = self._body(category_ids=[cat_id])

        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "review_categories") as mock_cats,
            patch.object(svc.db, "review_category_tags") as mock_tags,
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_r.find_unique = AsyncMock(side_effect=[existing, updated])
            mock_r.update = AsyncMock(return_value=updated)
            mock_cats.find_many = AsyncMock(return_value=[cat])
            mock_tags.delete_many = AsyncMock()
            mock_tags.create = AsyncMock(return_value=MagicMock())
            mock_er.find_many = AsyncMock(return_value=[])

            await svc.update_review(str(existing.review_id), body, reviewer_id)

        update_data = mock_r.update.call_args.kwargs["data"]
        assert "raw_points" in update_data

    async def test_raises_400_when_new_categories_invalid(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        body = self._body(category_ids=[uuid.uuid4()])

        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "review_categories") as mock_cats,
        ):
            mock_r.find_unique = AsyncMock(return_value=existing)
            mock_cats.find_many = AsyncMock(return_value=[])  # none found
            with pytest.raises(HTTPException) as exc:
                await svc.update_review(str(existing.review_id), body, reviewer_id)
        assert exc.value.status_code == 400

    async def test_deletes_old_tags_and_creates_new_ones(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        updated = _fake_review(reviewer_id=reviewer_id)
        cat = _fake_category(multiplier=1.2)
        body = self._body(category_ids=[uuid.uuid4()])

        with (
            patch.object(svc.db, "reviews") as mock_r,
            patch.object(svc.db, "review_categories") as mock_cats,
            patch.object(svc.db, "review_category_tags") as mock_tags,
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_r.find_unique = AsyncMock(side_effect=[existing, updated])
            mock_r.update = AsyncMock(return_value=updated)
            mock_cats.find_many = AsyncMock(return_value=[cat])
            mock_tags.delete_many = AsyncMock()
            mock_tags.create = AsyncMock(return_value=MagicMock())
            mock_er.find_many = AsyncMock(return_value=[])

            await svc.update_review(str(existing.review_id), body, reviewer_id)

        mock_tags.delete_many.assert_awaited_once()
        mock_tags.create.assert_awaited_once()

    async def test_returns_serialised_review_after_update(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        final = _fake_review(reviewer_id=reviewer_id)
        body = self._body(comment="Updated comment is properly long enough")

        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(side_effect=[existing, final])
            mock_r.update = AsyncMock(return_value=final)
            result = await svc.update_review(str(existing.review_id), body, reviewer_id)

        assert "review_id" in result
        assert "comment" in result

    async def test_updated_by_set_to_caller(self):
        reviewer_id = make_uuid()
        existing = _fake_review(reviewer_id=reviewer_id)
        updated = _fake_review(reviewer_id=reviewer_id)
        body = self._body(comment="Updated comment with sufficient length here")

        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_unique = AsyncMock(side_effect=[existing, updated])
            mock_r.update = AsyncMock(return_value=updated)
            await svc.update_review(str(existing.review_id), body, reviewer_id)

        assert mock_r.update.call_args.kwargs["data"]["updated_by"] == reviewer_id


# ─────────────────────────────────────────────────────────────────────────────
# get_review_stats_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReviewStatsInternal:
    async def test_returns_all_three_stat_keys(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count = AsyncMock(return_value=5)
            result = await svc.get_review_stats_internal(eid)
        assert set(result.keys()) == {"reviews_total", "reviews_this_month", "reviews_last_month"}

    async def test_calls_count_three_times(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count = AsyncMock(return_value=3)
            await svc.get_review_stats_internal(eid)
        assert mock_r.count.await_count == 3

    async def test_returns_correct_values(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count = AsyncMock(side_effect=[10, 3, 4])
            result = await svc.get_review_stats_internal(eid)
        assert result["reviews_total"]      == 10
        assert result["reviews_this_month"] == 3
        assert result["reviews_last_month"] == 4

    async def test_zero_counts_for_employee_with_no_reviews(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.count = AsyncMock(return_value=0)
            result = await svc.get_review_stats_internal(eid)
        assert result["reviews_total"] == 0
        assert result["reviews_this_month"] == 0
        assert result["reviews_last_month"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# get_recent_reviews_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRecentReviewsInternal:
    async def test_returns_list(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recent_reviews_internal(eid)
        assert isinstance(result, list)

    async def test_returns_serialised_reviews(self):
        eid = make_uuid()
        r1 = _fake_review(receiver_id=eid)
        r2 = _fake_review(receiver_id=eid)
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[r1, r2])
            result = await svc.get_recent_reviews_internal(eid)
        assert len(result) == 2
        assert "review_id" in result[0]

    async def test_default_limit_is_five(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.get_recent_reviews_internal(eid)
        assert mock_r.find_many.call_args.kwargs.get("take") == 5

    async def test_custom_limit_respected(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.get_recent_reviews_internal(eid, limit=10)
        assert mock_r.find_many.call_args.kwargs.get("take") == 10

    async def test_filters_by_receiver_id(self):
        eid = make_uuid()
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.get_recent_reviews_internal(eid)
        where = mock_r.find_many.call_args.kwargs.get("where", {})
        assert where.get("receiver_id") == eid


# ─────────────────────────────────────────────────────────────────────────────
# get_recognition_trend_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRecognitionTrendInternal:
    def _make_review_at(self, dt: datetime) -> MagicMock:
        r = _fake_review()
        r.review_at = dt
        return r

    async def test_returns_data_key(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("6m")
        assert "data" in result

    async def test_6m_returns_6_buckets(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("6m")
        assert len(result["data"]) == 6

    async def test_1y_returns_12_buckets(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("1y")
        assert len(result["data"]) == 12

    async def test_3m_returns_12_weekly_buckets(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("3m")
        assert len(result["data"]) == 12

    async def test_each_bucket_has_label_given_received(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("6m")
        for bucket in result["data"]:
            assert "label"    in bucket
            assert "given"    in bucket
            assert "received" in bucket

    async def test_reviews_counted_in_correct_bucket(self):
        """Reviews in the current month should appear in the last bucket."""
        now = datetime.now(timezone.utc)
        r = _fake_review()
        r.review_at = now.replace(day=1, hour=12)
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[r])
            result = await svc.get_recognition_trend_internal("6m")
        last_bucket = result["data"][-1]
        # The last bucket covers this month — the review should be counted
        assert last_bucket["received"] >= 1

    async def test_empty_reviews_gives_all_zeros(self):
        with patch.object(svc.db, "reviews") as mock_r:
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_trend_internal("6m")
        for bucket in result["data"]:
            assert bucket["given"]    == 0
            assert bucket["received"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# get_recognition_by_user_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRecognitionByUserInternal:
    def _make_employee(self, employee_id: str | None = None, department_id: str | None = None):
        e = MagicMock()
        e.employee_id   = employee_id or make_uuid()
        e.department_id = department_id or make_uuid()
        e.username      = "user_" + str(e.employee_id)[:8]
        return e

    def _make_dept(self, department_id: str | None = None):
        d = MagicMock()
        d.department_id   = department_id or make_uuid()
        d.department_name = "Engineering"
        return d

    async def test_returns_expected_keys(self):
        with (
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_e.find_many = AsyncMock(return_value=[])
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_by_user_internal("month", 1, 20)
        assert set(result.keys()) == {"items", "total", "page", "limit", "pages"}

    async def test_empty_employees_returns_empty_items(self):
        with (
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_e.find_many = AsyncMock(return_value=[])
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_by_user_internal("month", 1, 20)
        assert result["items"] == []
        assert result["total"] == 0

    async def test_counts_given_and_received_correctly(self):
        emp_id = make_uuid()
        emp    = self._make_employee(employee_id=emp_id)
        dept   = self._make_dept(department_id=str(emp.department_id))

        review_given    = _fake_review(reviewer_id=emp_id)
        review_received = _fake_review(receiver_id=emp_id)

        with (
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_e.find_many = AsyncMock(return_value=[emp])
            mock_r.find_many = AsyncMock(return_value=[review_given, review_received])
            mock_d.find_many = AsyncMock(return_value=[dept])
            result = await svc.get_recognition_by_user_internal("month", 1, 20)

        row = result["items"][0]
        assert row["given"]    == 1
        assert row["received"] == 1

    async def test_pagination_page_2(self):
        emps = [self._make_employee() for _ in range(25)]
        dept = self._make_dept()
        with (
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_e.find_many = AsyncMock(return_value=emps)
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[dept])
            result = await svc.get_recognition_by_user_internal("month", 2, 20)
        assert result["page"] == 2
        assert len(result["items"]) == 5  # 25 total, page 2 of 20

    async def test_all_ranges_accepted(self):
        for range_ in ("week", "month", "quarter", "year"):
            with (
                patch.object(svc.db, "employees")   as mock_e,
                patch.object(svc.db, "reviews")     as mock_r,
                patch.object(svc.db, "departments") as mock_d,
            ):
                mock_e.find_many = AsyncMock(return_value=[])
                mock_r.find_many = AsyncMock(return_value=[])
                mock_d.find_many = AsyncMock(return_value=[])
                result = await svc.get_recognition_by_user_internal(range_, 1, 20)
            assert "items" in result, f"Failed for range={range_}"

    async def test_sorted_by_given_descending(self):
        emp1 = self._make_employee()
        emp2 = self._make_employee()
        dept = self._make_dept()
        # emp2 gave 3, emp1 gave 1
        reviews = (
            [_fake_review(reviewer_id=str(emp2.employee_id))] * 3
            + [_fake_review(reviewer_id=str(emp1.employee_id))]
        )
        with (
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_e.find_many = AsyncMock(return_value=[emp1, emp2])
            mock_r.find_many = AsyncMock(return_value=reviews)
            mock_d.find_many = AsyncMock(return_value=[dept])
            result = await svc.get_recognition_by_user_internal("month", 1, 20)
        # First item should have more given
        assert result["items"][0]["given"] >= result["items"][1]["given"]


# ─────────────────────────────────────────────────────────────────────────────
# get_recognition_by_team_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetRecognitionByTeamInternal:
    def _make_employee(self, dept_id: str):
        e = MagicMock()
        e.employee_id   = make_uuid()
        e.department_id = dept_id
        return e

    def _make_dept(self, dept_id: str | None = None, name: str = "Engineering"):
        d = MagicMock()
        d.department_id   = dept_id or make_uuid()
        d.department_name = name
        return d

    async def test_returns_expected_keys(self):
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
        ):
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_by_team_internal("month", 1, 10)
        assert set(result.keys()) == {"items", "total", "page", "limit", "pages"}

    async def test_empty_departments_returns_empty(self):
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
        ):
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_by_team_internal("month", 1, 10)
        assert result["items"] == []

    async def test_counts_given_per_department(self):
        dept_id = make_uuid()
        dept    = self._make_dept(dept_id)
        emp1    = self._make_employee(dept_id)
        emp2    = self._make_employee(dept_id)
        reviews = [
            _fake_review(reviewer_id=str(emp1.employee_id)),
            _fake_review(reviewer_id=str(emp2.employee_id)),
        ]
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp1, emp2])
            mock_r.find_many = AsyncMock(return_value=reviews)
            result = await svc.get_recognition_by_team_internal("month", 1, 10)
        assert len(result["items"]) == 1
        row = result["items"][0]
        assert row["given"]   == 2
        assert row["members"] == 2

    async def test_all_ranges_work(self):
        for range_ in ("week", "month", "quarter", "year"):
            with (
                patch.object(svc.db, "departments") as mock_d,
                patch.object(svc.db, "employees")   as mock_e,
                patch.object(svc.db, "reviews")     as mock_r,
            ):
                mock_d.find_many = AsyncMock(return_value=[])
                mock_e.find_many = AsyncMock(return_value=[])
                mock_r.find_many = AsyncMock(return_value=[])
                result = await svc.get_recognition_by_team_internal(range_, 1, 10)
            assert "items" in result

    async def test_pagination_skip_applied(self):
        dept1 = self._make_dept(name="Eng")
        dept2 = self._make_dept(name="Sales")
        emp1  = self._make_employee(str(dept1.department_id))
        emp2  = self._make_employee(str(dept2.department_id))
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
            patch.object(svc.db, "reviews")     as mock_r,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept1, dept2])
            mock_e.find_many = AsyncMock(return_value=[emp1, emp2])
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.get_recognition_by_team_internal("month", 2, 1)
        # page=2, limit=1 → skip first item
        assert len(result["items"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# get_participation_internal
# ─────────────────────────────────────────────────────────────────────────────

class TestGetParticipationInternal:
    def _make_active_employee(self, dept_id: str | None = None):
        e = MagicMock()
        e.employee_id   = make_uuid()
        e.department_id = dept_id or make_uuid()
        status = MagicMock()
        status.status_code = "ACTIVE"
        e.status_master_employees_status_idTostatus_master = status
        return e

    def _make_inactive_employee(self):
        e = MagicMock()
        e.employee_id   = make_uuid()
        e.department_id = make_uuid()
        e.status_master_employees_status_idTostatus_master = None
        return e

    def _make_dept(self, dept_id: str | None = None):
        d = MagicMock()
        d.department_id   = dept_id or make_uuid()
        d.department_name = "Engineering"
        return d

    async def test_returns_pie_stats_and_by_department(self):
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            result = await svc.get_participation_internal()
        assert "pie" in result
        assert "stats" in result
        assert "by_department" in result

    async def test_zero_active_employees_gives_zero_rate(self):
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            result = await svc.get_participation_internal()
        assert result["stats"]["participation_rate"]       == 0.0
        assert result["stats"]["avg_reviews_per_employee"] == 0.0

    async def test_inactive_employees_excluded_from_rate(self):
        active   = self._make_active_employee()
        inactive = self._make_inactive_employee()
        dept     = self._make_dept(str(active.department_id))

        r = _fake_review(reviewer_id=str(active.employee_id))
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[r, r])  # all_reviews + recent_reviews
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[active, inactive])
            result = await svc.get_participation_internal()
        # Only 1 active employee, so total_employees should be 1
        assert result["stats"]["total_employees"] == 1

    async def test_participation_rate_calculated_correctly(self):
        dept_id = make_uuid()
        dept    = self._make_dept(dept_id)
        emp1    = self._make_active_employee(dept_id)
        emp2    = self._make_active_employee(dept_id)
        # emp1 participated (gave a review), emp2 did not
        review = _fake_review(reviewer_id=str(emp1.employee_id), receiver_id=str(emp1.employee_id))
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[review])
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp1, emp2])
            result = await svc.get_participation_internal()
        stats = result["stats"]
        assert stats["total_employees"] == 2
        assert stats["active_participants"] == 1
        assert stats["non_participants"] == 1
        assert stats["participation_rate"] == 50.0

    async def test_pie_has_two_entries(self):
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            result = await svc.get_participation_internal()
        assert len(result["pie"]) == 2

    async def test_stats_contains_all_expected_keys(self):
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            result = await svc.get_participation_internal()
        expected = {
            "total_employees", "active_participants", "non_participants",
            "participation_rate", "avg_reviews_per_employee", "avg_reviews_last_month",
        }
        assert expected.issubset(set(result["stats"].keys()))

    async def test_by_department_contains_dept_info(self):
        dept_id = make_uuid()
        dept    = self._make_dept(dept_id)
        emp     = self._make_active_employee(dept_id)
        review  = _fake_review(reviewer_id=str(emp.employee_id))
        with (
            patch.object(svc.db, "reviews")     as mock_r,
            patch.object(svc.db, "departments") as mock_d,
            patch.object(svc.db, "employees")   as mock_e,
        ):
            mock_r.find_many = AsyncMock(return_value=[review])
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            result = await svc.get_participation_internal()
        dept_rows = result["by_department"]
        assert len(dept_rows) == 1
        for key in ("department_id", "name", "active", "total", "rate"):
            assert key in dept_rows[0]
