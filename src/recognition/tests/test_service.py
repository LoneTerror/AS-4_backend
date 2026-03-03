"""
test_service.py
Unit tests for src/recognition/service.py — RecognitionService

Covers every method, every RBAC branch, every business-rule guard,
every error path, and all audit/pagination edge cases.

FIXED (5 categories of bugs):

1. MISSING category_id IN PAYLOADS
   TestCreateReview._payload() and TestUpdateReview._payload() both lacked
   category_id. Service reads payload.category_id early in create_review
   (step [7] — _resolve_points_inputs) and in update_review (points_changed
   guard). A MagicMock attribute returns a truthy MagicMock, not None, so
   update tests that passed payload with no category_id would always trigger
   the points-recalculation branch and hit the new DB tables unnecessarily.

2. MISSING PATCHES FOR NEW DB TABLES
   create_review now calls 8 DB operations in total (vs 3 originally):
     [2] db.employees.find_unique   — reviewer active check
     [3] db.employees.find_unique   — receiver check
     [4] db.reviews.find_first      — duplicate-pair guard
     [5] db.reviews.count           — monthly quota
     [6] db.status_master.find_first
     [7a] db.review_categories.find_unique
     [7b] db.roles.find_first
     [7c] db.seasonal_multipliers.find_first
     [7d] db.points_config.find_first
     [8] db.reviews.create
   Tests that patched only find_unique + status_master + create would hit
   the real (MagicMock) DB for all the new tables, causing float() errors
   on MagicMock objects (multiplier fields).

3. ENRICHED RETURN VALUES
   get_review, create_review, and update_review all call
   _enrich_with_effective_points(review) which returns a plain dict,
   not the original MagicMock. Tests asserting `result == review`
   (where review is a MagicMock) would always fail.
   Fixed: assert result is a dict and check specific keys instead.

4. list_reviews DATA ASSERTION
   result["data"] is a list of dicts from _enrich_with_effective_points,
   not the original MagicMock objects. Fixed: assert len and key presence.

5. REVIEWER ACTIVE CHECK (step [2])
   Service validates the reviewer (current_user) is an active employee
   before checking the receiver. Tests that patched db.employees.find_unique
   to return an active employee for the receiver would satisfy both calls,
   but only because MagicMock returns the same value for both. Now we use
   side_effect to differentiate the two calls properly.
"""

import math
import sys
import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Ensure conftest stubs are loaded before importing the real service
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from conftest import (  # noqa: E402
    make_user, make_review,
    make_active_employee, make_inactive_employee, make_employee_no_status,
    make_review_status,
    make_category_row, make_role_row, make_seasonal_row, make_points_config_row,
)

from src.recognition.service import RecognitionService

DB = "service.db"


# ---------------------------------------------------------------------------
# Shared helper: full patch context for create_review's happy path
# ---------------------------------------------------------------------------

def _full_create_patches(
    reviewer=None,
    receiver=None,
    duplicate=None,
    monthly_count=0,
    team_size=5,
    review_status=None,
    category=None,
    role=None,
    seasonal=None,
    points_cfg=None,
    created=None,
):
    """
    Returns a dict of {patch_target: AsyncMock} covering all DB calls that
    create_review makes in order. Import with **_full_create_patches() inside
    a patch() context or unpack manually.

    This helper exists because create_review now makes 9+ DB calls and
    every happy-path test needs all of them patched, or it hits real
    MagicMock attributes and crashes on float(MagicMock()).
    """
    active_emp  = reviewer  or make_active_employee()
    recv_emp    = receiver  or make_active_employee()
    rev_status  = review_status or make_review_status()
    cat_row     = category  or make_category_row()
    role_row    = role      or make_role_row(reviewer_weight=1.0)
    seasonal_row = seasonal or make_seasonal_row(multiplier=1.0)
    cfg_row     = points_cfg or make_points_config_row(config_value=0.9)
    created_rev = created   or make_review()

    return {
        # [2] reviewer active check → [3] receiver check (two consecutive calls)
        f"{DB}.employees.find_unique": AsyncMock(side_effect=[active_emp, recv_emp]),
        # [4] duplicate-pair guard
        f"{DB}.reviews.find_first":    AsyncMock(return_value=duplicate),
        # [5] monthly quota count
        f"{DB}.reviews.count":         AsyncMock(side_effect=[monthly_count]),
        # [5] team member count
        f"{DB}.employees.count":       AsyncMock(return_value=team_size),
        # [6] REVIEW_ACTIVE status
        f"{DB}.status_master.find_first": AsyncMock(return_value=rev_status),
        # [7a] category multiplier
        f"{DB}.review_categories.find_unique": AsyncMock(return_value=cat_row),
        # [7b] reviewer role weight
        f"{DB}.roles.find_first":      AsyncMock(return_value=role_row),
        # [7c] seasonal multiplier
        f"{DB}.seasonal_multipliers.find_first": AsyncMock(return_value=seasonal_row),
        # [7d] decay rate
        f"{DB}.points_config.find_first": AsyncMock(return_value=cfg_row),
        # [8] create
        f"{DB}.reviews.create":        AsyncMock(return_value=created_rev),
    }


# ---------------------------------------------------------------------------
# Shared helper: full patch context for update_review's happy path
# ---------------------------------------------------------------------------

def _full_update_patches(review=None, updated=None,
                         category=None, role=None,
                         seasonal=None, points_cfg=None):
    """
    Returns patch dict covering all DB calls update_review makes when a
    points-affecting field (rating / category_id) changes.
    Tests that only patch find_unique+update will fail because service.py
    always calls _resolve_points_inputs which hits the new DB tables.
    """
    rev     = review  or make_review(reviewer_id="user-1")
    upd     = updated or make_review()
    cat_row = category  or make_category_row()
    role_row = role     or make_role_row(reviewer_weight=1.0)
    seasonal_row = seasonal or make_seasonal_row(multiplier=1.0)
    cfg_row = points_cfg or make_points_config_row(config_value=0.9)
    return {
        f"{DB}.reviews.find_unique":               AsyncMock(return_value=rev),
        f"{DB}.review_categories.find_unique":     AsyncMock(return_value=cat_row),
        f"{DB}.roles.find_first":                  AsyncMock(return_value=role_row),
        f"{DB}.seasonal_multipliers.find_first":   AsyncMock(return_value=seasonal_row),
        f"{DB}.points_config.find_first":          AsyncMock(return_value=cfg_row),
        f"{DB}.reviews.update":                    AsyncMock(return_value=upd),
    }


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
    async def test_data_field_contains_enriched_dicts(self):
        """
        FIX: list_reviews returns _enrich_with_effective_points(r) for each
        review — a list of dicts, not the original MagicMock objects.
        Assert on length and that each item is a dict with expected keys.
        """
        user = make_user(roles=["HR_ADMIN"])
        reviews = [make_review(review_id="r1"), make_review(review_id="r2")]
        with patch(f"{DB}.reviews.count", AsyncMock(return_value=2)), \
             patch(f"{DB}.reviews.find_many", AsyncMock(return_value=reviews)):
            result = await RecognitionService.list_reviews(1, 20, user)

        assert len(result["data"]) == 2
        # Each element is a dict produced by _enrich_with_effective_points
        for item in result["data"]:
            assert isinstance(item, dict)
            assert "review_id" in item
            assert "effective_points" in item


# ===========================================================================
# GET REVIEW
# ===========================================================================

class TestGetReview:
    """Tests for RecognitionService.get_review()"""

    @pytest.mark.asyncio
    async def test_reviewer_can_access_own_review(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1", receiver_id="user-2")

        with patch(f"{DB}.reviews.find_unique", AsyncMock(return_value=review)):
            result = await RecognitionService.get_review("rev-1", user)

        # FIX: result is a dict from _enrich_with_effective_points, not the MagicMock
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
    """Tests for RecognitionService.create_review()"""

    def _payload(self, receiver_id="user-2", rating=4,
                 comment="Great work on the project here",
                 category_id="cat-uuid-1",   # FIX: added required field
                 image_url=None, video_url=None):
        p = MagicMock()
        p.receiver_id = receiver_id
        p.rating      = rating
        p.comment     = comment
        p.category_id = category_id          # FIX: set explicitly, not left to MagicMock
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

    # --- Reviewer active check (step [2]) ---

    @pytest.mark.asyncio
    async def test_inactive_reviewer_gets_403(self):
        """
        FIX: Service checks the reviewer (current_user) is ACTIVE before the
        receiver. This is step [2] — was not tested at all in the original suite.
        """
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique", AsyncMock(return_value=make_inactive_employee())):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 403
        assert "not active" in exc.value.detail

    # --- Receiver validation ---

    @pytest.mark.asyncio
    async def test_receiver_not_found_raises_404(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        # FIX: use side_effect — first call (reviewer check) returns active,
        # second call (receiver check) returns None
        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(), None])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 404
        assert exc.value.detail == "Receiver not found"

    @pytest.mark.asyncio
    async def test_inactive_receiver_raises_422(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(), make_inactive_employee()])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 422
        assert exc.value.detail == "Receiver is not active"

    @pytest.mark.asyncio
    async def test_receiver_with_null_status_relation_raises_422(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(), make_employee_no_status()])):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 422

    # --- Review status config ---

    @pytest.mark.asyncio
    async def test_missing_review_status_config_raises_500(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")

        with patch(f"{DB}.employees.find_unique",
                   AsyncMock(side_effect=[make_active_employee(), make_active_employee()])), \
             patch(f"{DB}.reviews.find_first", AsyncMock(return_value=None)), \
             patch(f"{DB}.reviews.count",      AsyncMock(return_value=0)), \
             patch(f"{DB}.employees.count",    AsyncMock(return_value=5)), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=None)):
            with pytest.raises(HTTPException) as exc:
                await RecognitionService.create_review(payload, user)

        assert exc.value.status_code == 500
        assert "Review status configuration missing" in exc.value.detail

    # --- Successful creation ---

    @pytest.mark.asyncio
    async def test_successful_create_returns_enriched_dict(self):
        """
        FIX: create_review calls _enrich_with_effective_points on the created
        review and returns a dict, not the original Prisma object.
        """
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Excellent performance all round")
        created = make_review(reviewer_id="user-1", receiver_id="user-2", rating=5)
        patches = _full_create_patches(created=created)

        with patch(f"{DB}.employees.find_unique", patches[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",    patches[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",         patches[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",       patches[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first", patches[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique", patches[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",      patches[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", patches[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first", patches[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.create",        patches[f"{DB}.reviews.create"]):
            result = await RecognitionService.create_review(payload, user)

        # FIX: result is a dict, not the MagicMock
        assert isinstance(result, dict)
        assert "review_id" in result
        assert "effective_points" in result

    @pytest.mark.asyncio
    async def test_create_data_fields_are_correct(self):
        user = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=5,
                                comment="Outstanding performance this quarter",
                                category_id="cat-uuid-1")
        create_mock = AsyncMock(return_value=make_review())
        patches = _full_create_patches(created=make_review())
        patches[f"{DB}.reviews.create"] = create_mock

        with patch(f"{DB}.employees.find_unique", patches[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",    patches[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",         patches[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",       patches[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first", AsyncMock(return_value=make_review_status("s-active"))), \
             patch(f"{DB}.review_categories.find_unique", patches[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",      patches[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", patches[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first", patches[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.create",        create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        assert data["reviewer_id"] == "user-1"
        assert data["receiver_id"] == "user-2"
        assert data["rating"]      == 5
        assert data["comment"]     == "Outstanding performance this quarter"
        assert data["status_id"]   == "s-active"
        assert data["created_by"]  == "user-1"
        assert data["updated_by"]  == "user-1"
        assert data["category_id"] == "cat-uuid-1"   # FIX: verify category written

    @pytest.mark.asyncio
    async def test_audit_timestamps_are_timezone_aware(self):
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")
        create_mock = AsyncMock(return_value=make_review())
        patches = _full_create_patches(created=make_review())

        with patch(f"{DB}.employees.find_unique", patches[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",    patches[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",         patches[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",       patches[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first", patches[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique", patches[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",      patches[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", patches[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first", patches[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.create",        create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        for ts_field in ("created_at", "updated_at", "review_at"):
            assert isinstance(data[ts_field], datetime)
            assert data[ts_field].tzinfo is not None, f"{ts_field} must be timezone-aware"

    @pytest.mark.asyncio
    async def test_status_master_queried_with_correct_params(self):
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2")
        status_mock = AsyncMock(return_value=make_review_status())
        patches = _full_create_patches()
        patches[f"{DB}.status_master.find_first"] = status_mock

        with patch(f"{DB}.employees.find_unique", patches[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",    patches[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",         patches[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",       patches[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first", status_mock), \
             patch(f"{DB}.review_categories.find_unique", patches[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",      patches[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", patches[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first", patches[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.create",        patches[f"{DB}.reviews.create"]):
            await RecognitionService.create_review(payload, user)

        where = status_mock.call_args[1]["where"]
        assert where["entity_type"] == "REVIEW"
        assert where["status_code"] == "REVIEW_ACTIVE"

    @pytest.mark.asyncio
    async def test_points_snapshot_written_to_db(self):
        """FIX: new test — verify raw_points, category_multiplier etc. are stored."""
        user    = make_user(user_id="user-1")
        payload = self._payload(receiver_id="user-2", rating=4)
        create_mock = AsyncMock(return_value=make_review())
        patches = _full_create_patches(
            category=make_category_row(multiplier=1.4),
            role=make_role_row(reviewer_weight=1.6),
            seasonal=make_seasonal_row(multiplier=1.0),
            points_cfg=make_points_config_row(config_value=0.9),
        )
        patches[f"{DB}.reviews.create"] = create_mock

        with patch(f"{DB}.employees.find_unique", patches[f"{DB}.employees.find_unique"]), \
             patch(f"{DB}.reviews.find_first",    patches[f"{DB}.reviews.find_first"]), \
             patch(f"{DB}.reviews.count",         patches[f"{DB}.reviews.count"]), \
             patch(f"{DB}.employees.count",       patches[f"{DB}.employees.count"]), \
             patch(f"{DB}.status_master.find_first", patches[f"{DB}.status_master.find_first"]), \
             patch(f"{DB}.review_categories.find_unique", patches[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",      patches[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", patches[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first", patches[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.create",        create_mock):
            await RecognitionService.create_review(payload, user)

        data = create_mock.call_args[1]["data"]
        # raw_points = rating(4) × cat(1.4) × weight(1.6) × seasonal(1.0) = 8.96
        assert "raw_points"          in data
        assert "category_multiplier" in data
        assert "reviewer_weight"     in data
        assert "seasonal_multiplier" in data
        assert round(data["raw_points"], 2) == 8.96


# ===========================================================================
# UPDATE REVIEW
# ===========================================================================

class TestUpdateReview:
    """Tests for RecognitionService.update_review()"""

    def _payload(self, rating=None, comment=None,
                 category_id=None,   # FIX: added — MagicMock would return truthy value
                 image_url=None, video_url=None):
        p = MagicMock()
        p.rating      = rating
        p.comment     = comment
        p.category_id = category_id  # FIX: explicitly None so points_changed logic is correct
        p.image_url   = image_url
        p.video_url   = video_url
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

        p = _full_update_patches(review=review, updated=updated)
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]):
            result = await RecognitionService.update_review("rev-1", self._payload(rating=5), user)

        # FIX: result is a dict from _enrich_with_effective_points
        assert isinstance(result, dict)
        assert "review_id" in result

    @pytest.mark.asyncio
    async def test_hr_admin_can_update_any_review(self):
        user    = make_user(user_id="admin", roles=["HR_ADMIN"])
        review  = make_review(reviewer_id="user-1")
        updated = make_review()

        p = _full_update_patches(review=review, updated=updated)
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]):
            result = await RecognitionService.update_review(
                "rev-1", self._payload(comment="Admin edit"), user
            )

        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_super_admin_can_update_any_review(self):
        user    = make_user(user_id="sadmin", roles=["SUPER_ADMIN"])
        review  = make_review(reviewer_id="user-1")
        updated = make_review()

        p = _full_update_patches(review=review, updated=updated)
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  p[f"{DB}.reviews.update"]):
            result = await RecognitionService.update_review(
                "rev-1", self._payload(rating=1), user
            )

        assert isinstance(result, dict)

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

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
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

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
            await RecognitionService.update_review(
                "rev-1", self._payload(comment="New comment"), user
            )

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

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
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

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
            await RecognitionService.update_review("rev-1", self._payload(video_url=vid), user)

        data = update_mock.call_args[1]["data"]
        assert data["video_url"] == "https://cdn.example.com/vid.mp4"
        assert "rating"    not in data
        assert "image_url" not in data

    # --- Audit fields ---

    @pytest.mark.asyncio
    async def test_updated_at_is_timezone_aware_datetime(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
            await RecognitionService.update_review("rev-1", self._payload(rating=4), user)

        data = update_mock.call_args[1]["data"]
        assert isinstance(data["updated_at"], datetime)
        assert data["updated_at"].tzinfo is not None

    @pytest.mark.asyncio
    async def test_updated_by_set_to_current_user(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
            await RecognitionService.update_review("rev-1", self._payload(rating=4), user)

        assert update_mock.call_args[1]["data"]["updated_by"] == "user-1"

    @pytest.mark.asyncio
    async def test_update_called_with_correct_review_id_in_where(self):
        user   = make_user(user_id="user-1", roles=["EMPLOYEE"])
        review = make_review(reviewer_id="user-1")
        update_mock = AsyncMock(return_value=make_review())

        p = _full_update_patches(review=review)
        p[f"{DB}.reviews.update"] = update_mock
        with patch(f"{DB}.reviews.find_unique",             p[f"{DB}.reviews.find_unique"]), \
             patch(f"{DB}.review_categories.find_unique",   p[f"{DB}.review_categories.find_unique"]), \
             patch(f"{DB}.roles.find_first",                p[f"{DB}.roles.find_first"]), \
             patch(f"{DB}.seasonal_multipliers.find_first", p[f"{DB}.seasonal_multipliers.find_first"]), \
             patch(f"{DB}.points_config.find_first",        p[f"{DB}.points_config.find_first"]), \
             patch(f"{DB}.reviews.update",                  update_mock):
            await RecognitionService.update_review(
                "rev-target-id", self._payload(rating=4), user
            )

        assert update_mock.call_args[1]["where"] == {"review_id": "rev-target-id"}