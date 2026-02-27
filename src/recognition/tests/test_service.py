"""
test_service.py
Unit tests for src/recognition/service.py — RecognitionService

Covers every method, every RBAC branch, every business-rule guard,
every error path, and all audit/pagination edge cases.
"""

import math
import sys
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Ensure conftest stubs are loaded before importing the real service
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))          # tests/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))  # project root

from conftest import (  # noqa: E402
    make_user, make_review,
    make_active_employee, make_inactive_employee, make_employee_no_status,
    make_review_status,
)

from service import RecognitionService  # noqa: E402

DB = "service.db"


# ===========================================================================
# LIST REVIEWS
# ===========================================================================

class TestListReviews:
    """Tests for RecognitionService.list_reviews()"""

    # --- RBAC filtering ---

    @pytest.mark.asyncio
    async def test_employee_sees_only_own_reviews(self):
        user = make_user(user_id="emp-1", roles=["EMPLOYEE"])
        count_mock = AsyncMock(return_value=2)
        find_mock  = AsyncMock(return_value=[make_review(), make_review()])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            result = await RecognitionService.list_reviews(1, 20, user)

        where = count_mock.call_args[1]["where"]
        assert "OR" in where
        assert {"reviewer_id": "emp-1"} in where["OR"]
        assert {"receiver_id": "emp-1"} in where["OR"]
        assert result["pagination"]["total"] == 2

    @pytest.mark.asyncio
    async def test_manager_sees_only_own_reviews(self):
        user = make_user(user_id="mgr-1", roles=["MANAGER"])
        count_mock = AsyncMock(return_value=3)
        find_mock  = AsyncMock(return_value=[make_review()] * 3)

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        where = count_mock.call_args[1]["where"]
        assert "OR" in where

    @pytest.mark.asyncio
    async def test_hr_admin_has_no_or_restriction(self):
        user = make_user(roles=["HR_ADMIN"])
        count_mock = AsyncMock(return_value=50)
        find_mock  = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        where = count_mock.call_args[1]["where"]
        assert "OR" not in where

    @pytest.mark.asyncio
    async def test_super_admin_has_no_or_restriction(self):
        user = make_user(roles=["SUPER_ADMIN"])
        count_mock = AsyncMock(return_value=100)
        find_mock  = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        where = count_mock.call_args[1]["where"]
        assert "OR" not in where

    @pytest.mark.asyncio
    async def test_user_with_employee_and_hr_admin_roles_gets_all(self):
        """HR_ADMIN in roles set overrides EMPLOYEE restriction"""
        user = make_user(roles=["EMPLOYEE", "HR_ADMIN"])
        count_mock = AsyncMock(return_value=10)
        find_mock  = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        where = count_mock.call_args[1]["where"]
        assert "OR" not in where

    # --- Pagination math ---

    @pytest.mark.asyncio
    async def test_skip_is_calculated_correctly(self):
        """Page 3, limit 10 → skip = 20"""
        user = make_user(roles=["HR_ADMIN"])
        find_mock = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", AsyncMock(return_value=0)), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(3, 10, user)

        kw = find_mock.call_args[1]
        assert kw["skip"] == 20
        assert kw["take"] == 10

    @pytest.mark.asyncio
    async def test_results_ordered_by_review_at_desc(self):
        user = make_user(roles=["HR_ADMIN"])
        find_mock = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", AsyncMock(return_value=0)), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        assert find_mock.call_args[1]["order"] == {"review_at": "desc"}

    @pytest.mark.asyncio
    async def test_pagination_metadata_mid_page(self):
        """55 items, page 2 of 3"""
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=55)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[make_review()] * 20)):
            result = await RecognitionService.list_reviews(2, 20, user)

        p = result["pagination"]
        assert p["current_page"] == 2
        assert p["per_page"] == 20
        assert p["total"] == 55
        assert p["total_pages"] == math.ceil(55 / 20)
        assert p["has_next"] is True
        assert p["has_previous"] is True

    @pytest.mark.asyncio
    async def test_first_page_has_previous_false(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=40)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(1, 20, user)

        assert result["pagination"]["has_previous"] is False
        assert result["pagination"]["has_next"] is True

    @pytest.mark.asyncio
    async def test_last_page_has_next_false(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=40)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(2, 20, user)

        assert result["pagination"]["has_next"] is False
        assert result["pagination"]["has_previous"] is True

    @pytest.mark.asyncio
    async def test_zero_results_pagination(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=0)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(1, 20, user)

        p = result["pagination"]
        assert p["total"] == 0
        assert p["total_pages"] == 0
        assert p["has_next"] is False
        assert p["has_previous"] is False

    @pytest.mark.asyncio
    async def test_single_item_single_page(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=1)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[make_review()])):
            result = await RecognitionService.list_reviews(1, 20, user)

        p = result["pagination"]
        assert p["total_pages"] == 1
        assert p["has_next"] is False
        assert p["has_previous"] is False

    @pytest.mark.asyncio
    async def test_data_field_contains_review_list(self):
        user = make_user(roles=["HR_ADMIN"])
        reviews = [make_review(), make_review()]
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=2)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=reviews)):
            result = await RecognitionService.list_reviews(1, 20, user)

        assert result["data"] == reviews


# ===========================================================================
# GET REVIEW
# ===========================================================================

class TestGetReview:
    """Tests for RecognitionService.get_review()"""

    @pytest.mark.asyncio
    async def test_reviewer_can_access_own_review(self):
        user    = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review  = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert result == review

    @pytest.mark.asyncio
    async def test_receiver_can_access_own_review(self):
        user    = make_user(user_id="user-2", roles=["EMPLOYEE"])
        review  = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert result == review

    @pytest.mark.asyncio
    async def test_hr_admin_can_access_any_review(self):
        user   = make_user(user_id="admin", roles=["HR_ADMIN"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert result == review

    @pytest.mark.asyncio
    async def test_super_admin_can_access_any_review(self):
        user   = make_user(user_id="sadmin", roles=["SUPER_ADMIN"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert result == review

    @pytest.mark.asyncio
    async def test_unrelated_employee_gets_403(self):
        user   = make_user(user_id="stranger", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.get_review("rev-1", user)

        assert exc.value.status_code == 403
        assert exc.value.detail == "Access denied"

    @pytest.mark.asyncio
    async def test_manager_not_involved_gets_403(self):
        user   = make_user(user_id="mgr-99", roles=["MANAGER"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.get_review("rev-1", user)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_review_not_found_raises_404(self):
        user = make_user(roles=["EMPLOYEE"])

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.get_review("ghost-id", user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Review not found"

    @pytest.mark.asyncio
    async def test_query_uses_correct_review_id(self):
        user       = make_user(user_id="user-1", roles=["HR_ADMIN"])
        find_mock  = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", find_mock):
            await RecognitionService.get_review("specific-id-xyz", user)

        assert find_mock.call_args[1]["where"] == {"review_id": "specific-id-xyz"}


# ===========================================================================
# CREATE REVIEW
# ===========================================================================

class TestCreateReview:
    """Tests for RecognitionService.create_review()"""

    def _payload(self, receiver_id="user-2", rating=4,
                 comment="Great work on the project here",
                 image_url=None, video_url=None):
        p = MagicMock()
        p.receiver_id = receiver_id
        p.rating      = rating
        p.comment     = comment
        p.image_url   = image_url
        p.video_url   = video_url
        return p

    # --- Self-review guard ---

    @pytest.mark.asyncio
    async def test_self_review_raises_422(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-1")

        with pytest.raises(HTTPException) as exc:
            await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 422
        assert "Self review" in exc.value.detail

    # --- Receiver validation ---

    @pytest.mark.asyncio
    async def test_receiver_not_found_raises_404(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Receiver not found"

    @pytest.mark.asyncio
    async def test_inactive_receiver_raises_422(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=make_inactive_employee())):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 422
        assert exc.value.detail == "Receiver is not active"

    @pytest.mark.asyncio
    async def test_receiver_with_null_status_relation_raises_422(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=make_employee_no_status())):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_receiver_lookup_uses_str_of_receiver_id(self):
        """UUID receiver_id must be cast to str before DB lookup"""
        import uuid
        uid = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id=uid)
        find_mock = AsyncMock(return_value=None)

        with patch(f"{DB}.employees.find_unique", find_mock):
            with pytest.raises(HTTPException):
                await RecognitionService.create_review(payload, user)

        assert find_mock.call_args[1]["where"]["employee_id"] == str(uid)

    # --- Review status config ---

    @pytest.mark.asyncio
    async def test_missing_review_status_config_raises_500(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 500
        assert "Review status configuration missing" in exc.value.detail

    # --- Successful creation ---

    @pytest.mark.asyncio
    async def test_successful_create_returns_review(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Excellent performance all round")
        created = make_review()

        with patch(f"{DB}.employees.find_unique",  AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status())), \
             patch(f"{DB}.reviews.create",          AsyncMock(return_value=created)):
            result = await RecognitionService.create_review(payload, user)

        assert result == created

    @pytest.mark.asyncio
    async def test_create_data_fields_are_correct(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Outstanding performance this quarter")
        create_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status("s-active"))), \
             patch(f"{DB}.reviews.create",           create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        assert data["reviewer_id"] == "user-1"
        assert data["receiver_id"] == "user-2"
        assert data["rating"]      == 5
        assert data["comment"]     == "Outstanding performance this quarter"
        assert data["status_id"]   == "s-active"
        assert data["created_by"]  == "user-1"
        assert data["updated_by"]  == "user-1"

    @pytest.mark.asyncio
    async def test_audit_timestamps_are_timezone_aware(self):
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")
        create_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status())), \
             patch(f"{DB}.reviews.create",           create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        for ts_field in ("created_at", "updated_at", "review_at"):
            assert isinstance(data[ts_field], datetime)
            assert data[ts_field].tzinfo is not None, f"{ts_field} must be timezone-aware"

    @pytest.mark.asyncio
    async def test_create_with_image_url_stringified(self):
        user = make_user(user_id="user-1")
        img = MagicMock()
        img.__str__ = lambda s: "https://cdn.example.com/img.jpg"
        payload = self._payload(receiver_id="user-2", image_url=img)
        create_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status())), \
             patch(f"{DB}.reviews.create",           create_mock):
            await RecognitionService.create_review(payload, user)

        assert create_mock.call_args[1]["data"]["image_url"] == "https://cdn.example.com/img.jpg"

    @pytest.mark.asyncio
    async def test_create_with_video_url_stringified(self):
        user = make_user(user_id="user-1")
        vid = MagicMock()
        vid.__str__ = lambda s: "https://cdn.example.com/vid.mp4"
        payload = self._payload(receiver_id="user-2", video_url=vid)
        create_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status())), \
             patch(f"{DB}.reviews.create",           create_mock):
            await RecognitionService.create_review(payload, user)

        assert create_mock.call_args[1]["data"]["video_url"] == "https://cdn.example.com/vid.mp4"

    @pytest.mark.asyncio
    async def test_create_none_urls_stored_as_none(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", image_url=None, video_url=None)
        create_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status())), \
             patch(f"{DB}.reviews.create",           create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        assert data["image_url"] is None
        assert data["video_url"] is None

    @pytest.mark.asyncio
    async def test_status_master_queried_with_correct_params(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")
        find_first_mock = AsyncMock(return_value=make_review_status())

        with patch(f"{DB}.employees.find_unique",   AsyncMock(return_value=make_active_employee())), \
             patch(f"{DB}.status_master.find_first", find_first_mock), \
             patch(f"{DB}.reviews.create",           AsyncMock(return_value=make_review())):
            await RecognitionService.create_review(payload, user)

        where = find_first_mock.call_args[1]["where"]
        assert where["entity_type"]  == "REVIEW"
        assert where["status_code"]  == "REVIEW_ACTIVE"


# ===========================================================================
# UPDATE REVIEW
# ===========================================================================

class TestUpdateReview:
    """Tests for RecognitionService.update_review()"""

    def _payload(self, rating=None, comment=None, image_url=None, video_url=None):
        p = MagicMock()
        p.rating     = rating
        p.comment    = comment
        p.image_url  = image_url
        p.video_url  = video_url
        return p

    # --- Not found ---

    @pytest.mark.asyncio
    async def test_review_not_found_raises_404(self):
        user = make_user(roles=["EMPLOYEE"])
        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review("rev-X", self._payload(rating=3), user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Review not found"

    # --- RBAC ---

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_gets_403(self):
        user   = make_user(user_id="stranger", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review("rev-1", self._payload(rating=3), user)

        assert exc.value.status_code == 403
        assert "Not allowed" in exc.value.detail

    @pytest.mark.asyncio
    async def test_receiver_cannot_update_review(self):
        """Only the reviewer (not receiver) is the owner for update purposes"""
        user   = make_user(user_id="user-2", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review("rev-1", self._payload(rating=3), user)

        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reviewer_can_update_own_review(self):
        user    = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review  = make_review(reviewer_id="user-1")
        updated = make_review(rating=5)

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      AsyncMock(return_value=updated)):
            result = await RecognitionService.update_review("rev-1", self._payload(rating=5), user)

        assert result == updated

    @pytest.mark.asyncio
    async def test_hr_admin_can_update_any_review(self):
        user    = make_user(user_id="admin", roles=["HR_ADMIN"])
        review  = make_review(reviewer_id="user-1")
        updated = make_review()

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      AsyncMock(return_value=updated)):
            result = await RecognitionService.update_review("rev-1", self._payload(comment="Admin edit"), user)

        assert result == updated

    @pytest.mark.asyncio
    async def test_super_admin_can_update_any_review(self):
        user    = make_user(user_id="sadmin", roles=["SUPER_ADMIN"])
        review  = make_review(reviewer_id="user-1")
        updated = make_review()

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      AsyncMock(return_value=updated)):
            result = await RecognitionService.update_review("rev-1", self._payload(rating=1), user)

        assert result == updated

    # --- Empty payload ---

    @pytest.mark.asyncio
    async def test_all_none_payload_raises_400(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review("rev-1", self._payload(), user)

        assert exc.value.status_code == 400
        assert exc.value.detail == "No fields provided for update"

    # --- Partial field updates ---

    @pytest.mark.asyncio
    async def test_only_rating_updated(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(rating=3), user)

        data = update_mock.call_args[1]["data"]
        assert data["rating"] == 3
        assert "comment"   not in data
        assert "image_url" not in data
        assert "video_url" not in data

    @pytest.mark.asyncio
    async def test_only_comment_updated(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(comment="New comment"), user)

        data = update_mock.call_args[1]["data"]
        assert data["comment"] == "New comment"
        assert "rating"    not in data
        assert "image_url" not in data

    @pytest.mark.asyncio
    async def test_only_image_url_updated(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        img    = MagicMock()
        img.__str__ = lambda s: "https://cdn.example.com/new.jpg"
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(image_url=img), user)

        data = update_mock.call_args[1]["data"]
        assert data["image_url"] == "https://cdn.example.com/new.jpg"
        assert "rating"    not in data
        assert "comment"   not in data
        assert "video_url" not in data

    @pytest.mark.asyncio
    async def test_only_video_url_updated(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        vid    = MagicMock()
        vid.__str__ = lambda s: "https://cdn.example.com/vid.mp4"
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(video_url=vid), user)

        data = update_mock.call_args[1]["data"]
        assert data["video_url"] == "https://cdn.example.com/vid.mp4"
        assert "rating"    not in data
        assert "image_url" not in data

    @pytest.mark.asyncio
    async def test_all_fields_updated_at_once(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        img = MagicMock(); img.__str__ = lambda s: "https://cdn.example.com/img.jpg"
        vid = MagicMock(); vid.__str__ = lambda s: "https://cdn.example.com/vid.mp4"
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review(
                "rev-1",
                self._payload(rating=5, comment="All updated", image_url=img, video_url=vid),
                user,
            )

        data = update_mock.call_args[1]["data"]
        assert data["rating"]    == 5
        assert data["comment"]   == "All updated"
        assert data["image_url"] == "https://cdn.example.com/img.jpg"
        assert data["video_url"] == "https://cdn.example.com/vid.mp4"

    # --- Audit fields ---

    @pytest.mark.asyncio
    async def test_updated_at_is_timezone_aware_datetime(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(rating=4), user)

        data = update_mock.call_args[1]["data"]
        assert isinstance(data["updated_at"], datetime)
        assert data["updated_at"].tzinfo is not None

    @pytest.mark.asyncio
    async def test_updated_by_set_to_current_user(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-1", self._payload(rating=4), user)

        assert update_mock.call_args[1]["data"]["updated_by"] == "user-1"

    @pytest.mark.asyncio
    async def test_update_called_with_correct_review_id_in_where(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)), \
             patch(f"{DB}.reviews.update",      update_mock):
            await RecognitionService.update_review("rev-target-id", self._payload(rating=4), user)

        assert update_mock.call_args[1]["where"] == {"review_id": "rev-target-id"}
