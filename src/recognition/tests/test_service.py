"""
test_service.py
Unit tests for src/recognition/service.py — RecognitionService

FIXED:
1. CATEGORY_IDS IS A LIST (plural)
   service.py calls `for cid in payload.category_ids` — the payload mock must
   set category_ids as a list of strings, not category_id as a single string.
   All _payload() helpers updated accordingly.

2. REMOVED make_points_config_row FROM _full_create_patches
   The current service.py no longer queries points_config at all (the
   multi-category refactor removed DECAY_RATE lookups). Patching
   db.points_config.find_first is harmless but was causing confusion;
   it has been removed from all patch helpers.

3. ADDED review_category_tags PATCHES
   create_review writes junction rows via db.review_category_tags.create,
   then fetches them again via db.review_category_tags.find_many.
   update_review also calls delete_many + create + find_many when
   category_ids change. All these must be patched or the MagicMock returns
   an async-incompatible object and the test crashes.

4. RESULT IS A DICT FROM _build_review_dict
   get_review, create_review, update_review all return
   _build_review_dict(review, tags) which is a plain dict, not the original
   Prisma MagicMock. Tests now assert isinstance(result, dict) and check
   for keys like "review_id" and "category_tags".

5. REMOVED _enrich_with_effective_points REFERENCES
   That function no longer exists; _build_review_dict is the replacement.
   Assertions updated to check "category_tags" instead of "effective_points".

6. TWO find_unique CALLS FOR EMPLOYEES IN create_review
   Service checks reviewer (step [2]) then receiver (step [3]) with
   two consecutive db.employees.find_unique calls. Patches use side_effect
   list to return different values per call.
"""

import math
import sys
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from conftest import (
    make_user, make_review,
    make_active_employee, make_inactive_employee, make_employee_no_status,
    make_review_status,
    make_category_row, make_role_row, make_seasonal_row,
)

from service import RecognitionService

DB = "service.db"


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------

def _full_create_patches(
    reviewer=None, receiver=None, duplicate=None,
    monthly_count=0, team_size=5, review_status=None,
    category=None, role=None, seasonal=None, created=None,
):
    """
    Returns a dict of all DB patches needed for a successful create_review call.

    FIXED:
    - employees.find_unique uses side_effect=[reviewer, receiver] because
      create_review calls it twice: once for the reviewer (step [2]) and
      once for the receiver (step [3]).
    - review_category_tags.create and .find_many are included because
      create_review writes junction rows then re-fetches them.
    - points_config.find_first removed — service.py no longer queries it.
    """
    return {
        f"{DB}.employees.find_unique": AsyncMock(
            side_effect=[
                reviewer or make_active_employee(),
                receiver or make_active_employee(),
            ]
        ),
        f"{DB}.reviews.find_first":              AsyncMock(return_value=duplicate),
        f"{DB}.reviews.count":                   AsyncMock(return_value=monthly_count),
        f"{DB}.employees.count":                 AsyncMock(return_value=team_size),
        f"{DB}.status_master.find_first":        AsyncMock(
            return_value=review_status or make_review_status()
        ),
        f"{DB}.review_categories.find_unique":   AsyncMock(
            return_value=category or make_category_row()
        ),
        f"{DB}.roles.find_first":                AsyncMock(
            return_value=role or make_role_row(reviewer_weight=1.0)
        ),
        f"{DB}.seasonal_multipliers.find_first": AsyncMock(
            return_value=seasonal or make_seasonal_row(multiplier=1.0)
        ),
        f"{DB}.reviews.create":                  AsyncMock(
            return_value=created or make_review()
        ),
        # Junction table: write one row per tag, then re-fetch for response
        f"{DB}.review_category_tags.create":     AsyncMock(return_value=MagicMock()),
        f"{DB}.review_category_tags.find_many":  AsyncMock(return_value=[]),
    }


def _make_tag(category_id="cat-1"):
    """Build a minimal review_category_tags row mock."""
    tag = MagicMock()
    tag.category_id = category_id
    return tag


def _full_update_patches(review=None, updated=None,
                         category=None, role=None, seasonal=None):
    """
    Returns all DB patches needed for a successful update_review call.

    FIXED:
    - review_category_tags.find_many is needed both when keeping existing tags
      (rating-only update) and for the final response build.
    - review_category_tags.delete_many + .create are needed when category_ids
      is supplied.
    - find_many uses side_effect to return [_make_tag()] on the 1st call
      (existing-category lookup when payload.category_ids is None) and []
      on the 2nd call (response-build fetch). This ensures _resolve_multipliers
      receives a non-empty category list instead of raising a 422.
    """
    default_review = review if review is not None else make_review(
        reviewer_id="user-1",
    )
    # find_many is called twice when payload.category_ids is None:
    #   1st call: fetch existing tags to get category IDs for _resolve_multipliers
    #   2nd call: re-fetch tags to build the response dict
    # We return a tag on the 1st call so _resolve_multipliers gets a non-empty
    # category list, then [] on subsequent calls (response build just needs the list).
    return {
        f"{DB}.reviews.find_unique":             AsyncMock(
            return_value=default_review
        ),
        f"{DB}.review_categories.find_unique":   AsyncMock(
            return_value=category or make_category_row()
        ),
        f"{DB}.roles.find_first":                AsyncMock(
            return_value=role or make_role_row(reviewer_weight=1.0)
        ),
        f"{DB}.seasonal_multipliers.find_first": AsyncMock(
            return_value=seasonal or make_seasonal_row(multiplier=1.0)
        ),
        f"{DB}.reviews.update":                  AsyncMock(
            return_value=updated or make_review()
        ),
        f"{DB}.review_category_tags.find_many":  AsyncMock(
            side_effect=[[_make_tag("cat-1")], []]
        ),
        f"{DB}.review_category_tags.delete_many": AsyncMock(return_value=None),
        f"{DB}.review_category_tags.create":     AsyncMock(return_value=MagicMock()),
    }


# ===========================================================================
# LIST REVIEWS
# ===========================================================================

class TestListReviews:

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

        assert "OR" not in count_mock.call_args[1]["where"]

    @pytest.mark.asyncio
    async def test_super_admin_has_no_or_restriction(self):
        user = make_user(roles=["SUPER_ADMIN"])
        count_mock = AsyncMock(return_value=100)
        find_mock  = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        assert "OR" not in count_mock.call_args[1]["where"]

    @pytest.mark.asyncio
    async def test_user_with_employee_and_hr_admin_roles_gets_all(self):
        user = make_user(roles=["EMPLOYEE", "HR_ADMIN"])
        count_mock = AsyncMock(return_value=10)
        find_mock  = AsyncMock(return_value=[])

        with patch(f"{DB}.reviews.count", count_mock), \
             patch(f"{DB}.reviews.find_many", find_mock):
            await RecognitionService.list_reviews(1, 20, user)

        assert "OR" not in count_mock.call_args[1]["where"]

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
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=55)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[make_review()] * 20)):
            result = await RecognitionService.list_reviews(2, 20, user)

        p = result["pagination"]
        assert p["current_page"] == 2
        assert p["per_page"]     == 20
        assert p["total"]        == 55
        assert p["total_pages"]  == math.ceil(55 / 20)
        assert p["has_next"]     is True
        assert p["has_previous"] is True

    @pytest.mark.asyncio
    async def test_first_page_has_previous_false(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=40)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(1, 20, user)

        assert result["pagination"]["has_previous"] is False
        assert result["pagination"]["has_next"]     is True

    @pytest.mark.asyncio
    async def test_last_page_has_next_false(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=40)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(2, 20, user)

        assert result["pagination"]["has_next"]     is False
        assert result["pagination"]["has_previous"] is True

    @pytest.mark.asyncio
    async def test_zero_results_pagination(self):
        user = make_user(roles=["HR_ADMIN"])
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=0)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=[])):
            result = await RecognitionService.list_reviews(1, 20, user)

        p = result["pagination"]
        assert p["total"]        == 0
        assert p["total_pages"]  == 0
        assert p["has_next"]     is False
        assert p["has_previous"] is False

    @pytest.mark.asyncio
    async def test_data_field_contains_dicts_with_category_tags(self):
        """
        FIXED: list_reviews returns _build_review_dict(r, tags) per row —
        a list of dicts, not the original MagicMock objects.
        Each dict must contain 'review_id' and 'category_tags'.
        """
        user = make_user(roles=["HR_ADMIN"])
        reviews = [make_review(review_id="r1"), make_review(review_id="r2")]
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=2)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=reviews)):
            result = await RecognitionService.list_reviews(1, 20, user)

        assert len(result["data"]) == 2
        for item in result["data"]:
            assert isinstance(item, dict)
            assert "review_id"    in item
            assert "category_tags" in item


# ===========================================================================
# GET REVIEW
# ===========================================================================

class TestGetReview:

    @pytest.mark.asyncio
    async def test_reviewer_can_access_own_review(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        # FIXED: result is a dict from _build_review_dict, not the MagicMock
        assert isinstance(result, dict)
        assert result["reviewer_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_receiver_can_access_own_review(self):
        user   = make_user(user_id="user-2", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert isinstance(result, dict)
        assert result["receiver_id"] == "user-2"

    @pytest.mark.asyncio
    async def test_hr_admin_can_access_any_review(self):
        user   = make_user(user_id="admin", roles=["HR_ADMIN"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_super_admin_can_access_any_review(self):
        user   = make_user(user_id="sadmin", roles=["SUPER_ADMIN"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        assert isinstance(result, dict)

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
        user      = make_user(user_id="user-1", roles=["HR_ADMIN"])
        find_mock = AsyncMock(return_value=make_review())

        with patch(f"{DB}.reviews.find_unique", find_mock):
            await RecognitionService.get_review("specific-id-xyz", user)

        assert find_mock.call_args[1]["where"] == {"review_id": "specific-id-xyz"}


# ===========================================================================
# CREATE REVIEW
# ===========================================================================

class TestCreateReview:

    def _payload(self, receiver_id="user-2", rating=4,
                 comment="Great work on the project here",
                 category_ids=None,
                 image_url=None, video_url=None):
        """
        FIXED: category_ids is a list of strings matching the real schema.
        Using a MagicMock default for this field was wrong — MagicMock is
        truthy and iterable in unexpected ways.
        """
        p = MagicMock()
        p.receiver_id  = receiver_id
        p.rating       = rating
        p.comment      = comment
        p.category_ids = category_ids if category_ids is not None else ["cat-uuid-1"]
        p.image_url    = image_url
        p.video_url    = video_url
        return p

    @pytest.mark.asyncio
    async def test_self_review_raises_422(self):
        user = make_user(user_id="user-1")
        with pytest.raises(HTTPException) as exc:
            await RecognitionService.create_review(
                self._payload(receiver_id="user-1"), user
            )
        assert exc.value.status_code == 422
        assert "Self review" in exc.value.detail

    @pytest.mark.asyncio
    async def test_inactive_reviewer_gets_403(self):
        user = make_user(user_id="user-1")
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(return_value=make_inactive_employee())):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(self._payload(), user)
        assert exc.value.status_code == 403
        assert "not active" in exc.value.detail

    @pytest.mark.asyncio
    async def test_receiver_not_found_raises_404(self):
        user = make_user(user_id="user-1")
        # FIXED: side_effect=[reviewer_result, receiver_result]
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(), None])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(self._payload(), user)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Receiver not found"

    @pytest.mark.asyncio
    async def test_inactive_receiver_raises_422(self):
        user = make_user(user_id="user-1")
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(),
                                          make_inactive_employee()])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(self._payload(), user)
        assert exc.value.status_code == 422
        assert exc.value.detail == "Receiver is not active"

    @pytest.mark.asyncio
    async def test_receiver_with_null_status_relation_raises_422(self):
        user = make_user(user_id="user-1")
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(),
                                          make_employee_no_status()])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(self._payload(), user)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_review_status_config_raises_500(self):
        user = make_user(user_id="user-1")
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(),
                                          make_active_employee()])), \
             patch(f"{DB}.reviews.find_first", AsyncMock(return_value=None)), \
             patch(f"{DB}.reviews.count",      AsyncMock(return_value=0)), \
             patch(f"{DB}.employees.count",    AsyncMock(return_value=5)), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(self._payload(), user)
        assert exc.value.status_code == 500
        assert "Review status configuration missing" in exc.value.detail

    @pytest.mark.asyncio
    async def test_successful_create_returns_dict(self):
        """
        FIXED: create_review returns _build_review_dict(review, tags) — a
        plain dict, not the Prisma MagicMock.
        """
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Excellent performance all round")
        p = _full_create_patches(created=make_review(reviewer_id="user-1"))

        with patch(f"{DB}.employees.find_unique",           p[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",              p[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",                   p[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",                 p[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first",        p[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.create",                  p[f"{DB}.reviews.create"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]):
            result = await RecognitionService.create_review(payload, user)

        assert isinstance(result, dict)
        assert "review_id"    in result
        assert "category_tags" in result

    @pytest.mark.asyncio
    async def test_create_data_fields_are_correct(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Outstanding performance this quarter",
                                category_ids=["cat-uuid-1"])
        create_mock = AsyncMock(return_value=make_review())
        p = _full_create_patches()
        p[f"{DB}.reviews.create"] = create_mock

        with patch(f"{DB}.employees.find_unique",           p[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",              p[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",                   p[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",                 p[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first",        AsyncMock(return_value=make_review_status("s-active"))), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.create",                  create_mock), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        assert data["reviewer_id"] == "user-1"
        assert data["receiver_id"] == "user-2"
        assert data["rating"]      == 5
        assert data["comment"]     == "Outstanding performance this quarter"
        assert data["status_id"]   == "s-active"
        assert data["created_by"]  == "user-1"
        assert data["updated_by"]  == "user-1"
        assert "raw_points"        in data   # points snapshot written

    @pytest.mark.asyncio
    async def test_audit_timestamps_are_timezone_aware(self):
        user    = make_user(user_id="user-1")
        payload = self._payload()
        create_mock = AsyncMock(return_value=make_review())
        p = _full_create_patches()
        p[f"{DB}.reviews.create"] = create_mock

        with patch(f"{DB}.employees.find_unique",           p[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",              p[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",                   p[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",                 p[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first",        p[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.create",                  create_mock), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        for ts_field in ("created_at", "updated_at", "review_at"):
            assert isinstance(data[ts_field], datetime)
            assert data[ts_field].tzinfo is not None, f"{ts_field} must be tz-aware"

    @pytest.mark.asyncio
    async def test_status_master_queried_with_correct_params(self):
        user    = make_user(user_id="user-1")
        payload = self._payload()
        status_mock = AsyncMock(return_value=make_review_status())
        p = _full_create_patches()
        p[f"{DB}.status_master.find_first"] = status_mock

        with patch(f"{DB}.employees.find_unique",           p[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",              p[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",                   p[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",                 p[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first",        status_mock), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.create",                  p[f"{DB}.reviews.create"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]):
            await RecognitionService.create_review(payload, user)

        where = status_mock.call_args[1]["where"]
        assert where["entity_type"] == "REVIEW"
        assert where["status_code"] == "REVIEW_ACTIVE"

    @pytest.mark.asyncio
    async def test_points_snapshot_written_to_db(self):
        """
        FIXED: raw_points = rating(4) × cat_total(1.4) × weight(1.6) × seasonal(1.0)
        = 8.96.  category_multiplier/reviewer_weight/seasonal_multiplier columns
        were removed; only raw_points remains on the reviews table.
        """
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=4)
        create_mock = AsyncMock(return_value=make_review())
        p = _full_create_patches(
            category=make_category_row(multiplier=1.4),
            role=make_role_row(reviewer_weight=1.6),
            seasonal=make_seasonal_row(multiplier=1.0),
        )
        p[f"{DB}.reviews.create"] = create_mock

        with patch(f"{DB}.employees.find_unique",           p[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",              p[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",                   p[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",                 p[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first",        p[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.create",                  create_mock), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        assert "raw_points" in data
        # 4 × 1.4 × 1.6 × 1.0 = 8.96
        assert round(data["raw_points"], 2) == 8.96


# ===========================================================================
# UPDATE REVIEW
# ===========================================================================

class TestUpdateReview:

    def _payload(self, rating=None, comment=None,
                 category_ids=None,
                 image_url=None, video_url=None):
        """
        FIXED: category_ids explicitly set to None (not a truthy MagicMock).
        service.py checks `payload.category_ids is not None` to decide
        whether to replace tags — a MagicMock default would always trigger
        the tag-replacement branch.
        """
        p = MagicMock()
        p.rating       = rating
        p.comment      = comment
        p.category_ids = category_ids  # None = keep existing tags
        p.image_url    = image_url
        p.video_url    = video_url
        return p

    @pytest.mark.asyncio
    async def test_review_not_found_raises_404(self):
        user = make_user(roles=["EMPLOYEE"])
        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review(
                    "rev-X", self._payload(rating=3), user
                )
        assert exc.value.status_code == 404
        assert exc.value.detail == "Review not found"

    @pytest.mark.asyncio
    async def test_non_owner_non_admin_gets_403(self):
        user   = make_user(user_id="stranger", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review(
                    "rev-1", self._payload(rating=3), user
                )
        assert exc.value.status_code == 403
        assert "Not allowed" in exc.value.detail

    @pytest.mark.asyncio
    async def test_receiver_cannot_update_review(self):
        user   = make_user(user_id="user-2", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review(
                    "rev-1", self._payload(rating=3), user
                )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_reviewer_can_update_own_review(self):
        user    = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review  = make_review(reviewer_id="user-1", review_category_tags=[])
        updated = make_review(rating=5)
        p = _full_update_patches(review=review, updated=updated)

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            result = await RecognitionService.update_review(
                "rev-1", self._payload(rating=5), user
            )

        # FIXED: result is a dict from _build_review_dict
        assert isinstance(result, dict)
        assert "review_id" in result

    @pytest.mark.asyncio
    async def test_hr_admin_can_update_any_review(self):
        user   = make_user(user_id="admin", roles=["HR_ADMIN"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        p = _full_update_patches(review=review)

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            result = await RecognitionService.update_review(
                "rev-1", self._payload(comment="Admin edit"), user
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_super_admin_can_update_any_review(self):
        user   = make_user(user_id="sadmin", roles=["SUPER_ADMIN"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        p = _full_update_patches(review=review)

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            result = await RecognitionService.update_review(
                "rev-1", self._payload(rating=1), user
            )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_all_none_payload_raises_400(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.update_review(
                    "rev-1", self._payload(), user
                )
        assert exc.value.status_code == 400
        assert exc.value.detail == "No fields provided for update"

    @pytest.mark.asyncio
    async def test_only_rating_written_to_db(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        update_mock = AsyncMock(return_value=make_review())
        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            await RecognitionService.update_review(
                "rev-1", self._payload(rating=3), user
            )

        data = update_mock.call_args[1]["data"]
        assert data["rating"] == 3
        assert "comment"   not in data
        assert "image_url" not in data
        assert "video_url" not in data

    @pytest.mark.asyncio
    async def test_only_comment_written_to_db(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())
        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            await RecognitionService.update_review(
                "rev-1", self._payload(comment="New comment"), user
            )

        data = update_mock.call_args[1]["data"]
        assert data["comment"] == "New comment"
        assert "rating"    not in data
        assert "image_url" not in data

    @pytest.mark.asyncio
    async def test_updated_at_is_timezone_aware_datetime(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        update_mock = AsyncMock(return_value=make_review())
        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            await RecognitionService.update_review(
                "rev-1", self._payload(rating=4), user
            )

        data = update_mock.call_args[1]["data"]
        assert isinstance(data["updated_at"], datetime)
        assert data["updated_at"].tzinfo is not None

    @pytest.mark.asyncio
    async def test_updated_by_set_to_current_user(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        update_mock = AsyncMock(return_value=make_review())
        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            await RecognitionService.update_review(
                "rev-1", self._payload(rating=4), user
            )

        assert update_mock.call_args[1]["data"]["updated_by"] == "user-1"

    @pytest.mark.asyncio
    async def test_update_called_with_correct_review_id_in_where(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", review_category_tags=[])
        update_mock = AsyncMock(return_value=make_review())
        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock

        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock), \
             patch(f"{DB}.review_category_tags.find_many",  p[f"{DB}.review_category_tags.find_many"]), \
             patch(f"{DB}.review_category_tags.delete_many",p[f"{DB}.review_category_tags.delete_many"]), \
             patch(f"{DB}.review_category_tags.create",     p[f"{DB}.review_category_tags.create"]):
            await RecognitionService.update_review(
                "rev-target-id", self._payload(rating=4), user
            )

        assert update_mock.call_args[1]["where"] == {"review_id": "rev-target-id"}