"""
tests/test_router_integration.py
──────────────────────────────────
Integration tests for the FastAPI routers (router.py + internal_router.py).

KEY: The router imports service functions BY NAME at module load time:
    from src.recognition.service import list_reviews, create_review, ...
So patches must target `src.recognition.router.<fn>` (the router's local
binding), NOT `src.recognition.service.<fn>`.

Internal router imports via `from src.recognition import service`, so those
patches target `src.recognition.service.<fn>` as normal.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from conftest import _fake_category, _fake_review, make_uuid
import src.recognition.service as svc
import src.common.dependencies as deps
from src.recognition.router import router as recognition_router
from src.recognition.router import categories_router
from src.recognition.internal_router import router as internal_router

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

# Patch target: router module's local names (imported at load time)
_ROUTER = "src.recognition.router"

def _make_app() -> FastAPI:
    app = FastAPI(root_path="/aabhar/v1/recognitions")
    app.include_router(recognition_router)
    app.include_router(categories_router)
    app.include_router(internal_router)
    return app


def _override_auth(app: FastAPI, roles=None):
    """
    Replace check_route_permission with a zero-arg callable so FastAPI
    doesn't try to parse its parameters as query params.
    """
    user = deps.CurrentUser(id=make_uuid(), email="test@test.com", roles=roles or ["SUPER_ADMIN"])

    async def _no_auth():
        return user

    app.dependency_overrides[deps.check_route_permission] = _no_auth
    return user


def _paginated(items=None):
    items = items or []
    return {
        "data": items,
        "pagination": {
            "current_page": 1, "per_page": 20, "total": len(items),
            "total_pages": 1 if items else 0,
            "has_next": False, "has_previous": False,
        },
    }


def _serialised_review(r=None):
    r = r or _fake_review()
    return {
        "review_id":      str(r.review_id),
        "reviewer_id":    str(r.reviewer_id),
        "receiver_id":    str(r.receiver_id),
        "comment":        r.comment,
        "status_id":      str(r.status_id),
        "review_at":      r.review_at.isoformat(),
        "created_at":     r.created_at.isoformat(),
        "created_by":     str(r.created_by),
        "updated_at":     r.updated_at.isoformat(),
        "updated_by":     str(r.updated_by),
        "raw_points":     r.raw_points,
        "category_tags":  [],
        "category_ids":   [],
        "category_codes": [],
    }


def _serialised_category(c=None):
    c = c or _fake_category()
    return {
        "category_id":   str(c.category_id),
        "category_code": c.category_code,
        "category_name": c.category_name,
        "multiplier":    float(c.multiplier),
        "is_active":     c.is_active,
    }


@pytest.fixture
def app():
    a = _make_app()
    _override_auth(a)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# GET /review-categories
# ─────────────────────────────────────────────────────────────────────────────

class TestListReviewCategoriesRoute:
    def test_200_response(self, client):
        with patch(f"{_ROUTER}.list_review_categories", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/review-categories")
        assert resp.status_code == 200

    def test_response_has_data_and_pagination(self, client):
        with patch(f"{_ROUTER}.list_review_categories", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/review-categories")
        body = resp.json()
        assert "data" in body and "pagination" in body

    def test_active_only_forwarded(self, client):
        with patch(f"{_ROUTER}.list_review_categories", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            client.get("/review-categories?active_only=true")
        m.assert_awaited_once()
        _, kwargs = m.call_args
        assert kwargs.get("active_only") is True

    def test_page_and_size_forwarded(self, client):
        with patch(f"{_ROUTER}.list_review_categories", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            client.get("/review-categories?page=2&page_size=5")
        _, kwargs = m.call_args
        assert kwargs.get("page") == 2
        assert kwargs.get("limit") == 5

    def test_page_size_too_large_returns_422(self, client):
        resp = client.get("/review-categories?page_size=999")
        assert resp.status_code == 422

    def test_active_false_returns_all(self, client):
        with patch(f"{_ROUTER}.list_review_categories", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/review-categories?active_only=false")
        assert resp.status_code == 200
        _, kwargs = m.call_args
        assert kwargs.get("active_only") is False


# ─────────────────────────────────────────────────────────────────────────────
# POST /review-categories
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateReviewCategoryRoute:
    VALID = {"category_code": "INNOVATION", "category_name": "Innovation", "multiplier": 1.4}

    def test_201_on_valid_payload(self, client):
        with patch(f"{_ROUTER}.create_review_category", new_callable=AsyncMock) as m:
            m.return_value = _serialised_category()
            resp = client.post("/review-categories", json=self.VALID)
        assert resp.status_code == 201

    def test_missing_multiplier_returns_422(self, client):
        resp = client.post("/review-categories", json={"category_code": "X", "category_name": "Y"})
        assert resp.status_code == 422

    def test_negative_multiplier_returns_422(self, client):
        resp = client.post("/review-categories", json={**self.VALID, "multiplier": -1.0})
        assert resp.status_code == 422

    def test_zero_multiplier_returns_422(self, client):
        resp = client.post("/review-categories", json={**self.VALID, "multiplier": 0.0})
        assert resp.status_code == 422

    def test_duplicate_returns_409(self, client):
        with patch(f"{_ROUTER}.create_review_category", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="Duplicate")
            resp = client.post("/review-categories", json=self.VALID)
        assert resp.status_code == 409

    def test_extra_fields_returns_422(self, client):
        resp = client.post("/review-categories", json={**self.VALID, "bogus": "x"})
        assert resp.status_code == 422

    def test_code_gets_uppercased(self, client):
        with patch(f"{_ROUTER}.create_review_category", new_callable=AsyncMock) as m:
            m.return_value = _serialised_category()
            client.post("/review-categories", json={**self.VALID, "category_code": "innovation"})
        # Service receives the uppercased value from the schema validator
        payload = m.call_args.args[0]
        assert payload.category_code == "INNOVATION"


# ─────────────────────────────────────────────────────────────────────────────
# PUT /review-categories/{id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateReviewCategoryRoute:
    def test_200_on_valid_update(self, client):
        with patch(f"{_ROUTER}.update_review_category", new_callable=AsyncMock) as m:
            m.return_value = _serialised_category()
            resp = client.put(f"/review-categories/{uuid.uuid4()}", json={"multiplier": 1.9})
        assert resp.status_code == 200

    def test_404_when_not_found(self, client):
        with patch(f"{_ROUTER}.update_review_category", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Not found")
            resp = client.put(f"/review-categories/{uuid.uuid4()}", json={"multiplier": 1.2})
        assert resp.status_code == 404

    def test_invalid_uuid_path_returns_422(self, client):
        resp = client.put("/review-categories/not-a-uuid", json={"multiplier": 1.0})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.put(f"/review-categories/{uuid.uuid4()}", json={})
        assert resp.status_code == 422

    def test_deactivate_category(self, client):
        with patch(f"{_ROUTER}.update_review_category", new_callable=AsyncMock) as m:
            m.return_value = {**_serialised_category(), "is_active": False}
            resp = client.put(f"/review-categories/{uuid.uuid4()}", json={"is_active": False})
        assert resp.status_code == 200

    def test_update_name_and_multiplier(self, client):
        with patch(f"{_ROUTER}.update_review_category", new_callable=AsyncMock) as m:
            m.return_value = _serialised_category()
            resp = client.put(
                f"/review-categories/{uuid.uuid4()}",
                json={"category_name": "Updated Name", "multiplier": 2.0},
            )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# GET /reviews
# ─────────────────────────────────────────────────────────────────────────────

class TestListReviewsRoute:
    def test_200_no_filter(self, client):
        with patch(f"{_ROUTER}.list_reviews", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/reviews")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        with patch(f"{_ROUTER}.list_reviews", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/reviews")
        body = resp.json()
        assert "data" in body and "pagination" in body

    def test_employee_role_calls_list_reviews_twice(self):
        """EMPLOYEE role: router calls list_reviews once as reviewer and once as receiver."""
        a = _make_app()
        _override_auth(a, roles=["EMPLOYEE"])
        c = TestClient(a, raise_server_exceptions=False)
        with patch(f"{_ROUTER}.list_reviews", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = c.get("/reviews")
        assert resp.status_code == 200
        assert m.await_count == 2, f"Expected 2 list_reviews calls for EMPLOYEE, got {m.await_count}"

    def test_no_employee_id_calls_list_reviews_for_roles(self, client):
        """SUPER_ADMIN gets all reviews with no filter."""
        with patch(f"{_ROUTER}.list_reviews", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = client.get("/reviews")
        assert resp.status_code == 200

    def test_hr_admin_can_list_all(self):
        a = _make_app()
        _override_auth(a, roles=["HR_ADMIN"])
        c = TestClient(a, raise_server_exceptions=False)
        with patch(f"{_ROUTER}.list_reviews", new_callable=AsyncMock) as m:
            m.return_value = _paginated()
            resp = c.get("/reviews")
        assert resp.status_code == 200

    def test_invalid_page_returns_422(self, client):
        resp = client.get("/reviews?page=0")
        assert resp.status_code == 422

    def test_page_size_too_large_returns_422(self, client):
        resp = client.get("/reviews?page_size=999")
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /reviews/{id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetReviewRoute:
    def test_200_returns_review(self, client):
        with patch(f"{_ROUTER}.get_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.get(f"/reviews/{uuid.uuid4()}")
        assert resp.status_code == 200

    def test_response_contains_review_fields(self, client):
        ser = _serialised_review()
        with patch(f"{_ROUTER}.get_review", new_callable=AsyncMock, return_value=ser):
            resp = client.get(f"/reviews/{uuid.uuid4()}")
        body = resp.json()
        for field in ("review_id", "comment", "reviewer_id", "receiver_id"):
            assert field in body

    def test_404_for_missing_review(self, client):
        with patch(f"{_ROUTER}.get_review", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Review not found")
            resp = client.get(f"/reviews/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_invalid_uuid_returns_422(self, client):
        resp = client.get("/reviews/not-a-uuid")
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# POST /reviews
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateReviewRoute:
    VALID = {
        "receiver_id":  str(uuid.uuid4()),
        "category_ids": [str(uuid.uuid4())],
        "comment":      "Excellent work on the full project scope",
    }

    def test_201_on_valid_payload(self, client):
        with patch(f"{_ROUTER}.create_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.post("/reviews", json=self.VALID)
        assert resp.status_code == 201

    def test_missing_comment_returns_422(self, client):
        bad = {k: v for k, v in self.VALID.items() if k != "comment"}
        resp = client.post("/reviews", json=bad)
        assert resp.status_code == 422

    def test_comment_too_short_returns_422(self, client):
        resp = client.post("/reviews", json={**self.VALID, "comment": "short"})
        assert resp.status_code == 422

    def test_six_categories_returns_422(self, client):
        bad = {**self.VALID, "category_ids": [str(uuid.uuid4()) for _ in range(6)]}
        resp = client.post("/reviews", json=bad)
        assert resp.status_code == 422

    def test_empty_categories_returns_422(self, client):
        resp = client.post("/reviews", json={**self.VALID, "category_ids": []})
        assert resp.status_code == 422

    def test_duplicate_category_ids_returns_422(self, client):
        same = str(uuid.uuid4())
        resp = client.post("/reviews", json={**self.VALID, "category_ids": [same, same]})
        assert resp.status_code == 422

    def test_invalid_category_returns_400(self, client):
        with patch(f"{_ROUTER}.create_review", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="Invalid category")
            resp = client.post("/reviews", json=self.VALID)
        assert resp.status_code == 400

    def test_five_categories_accepted(self, client):
        cats = [str(uuid.uuid4()) for _ in range(5)]
        with patch(f"{_ROUTER}.create_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.post("/reviews", json={**self.VALID, "category_ids": cats})
        assert resp.status_code == 201

    def test_with_image_and_video_url(self, client):
        payload = {
            **self.VALID,
            "image_url": "https://cdn.example.com/img.jpg",
            "video_url": "https://cdn.example.com/vid.mp4",
        }
        with patch(f"{_ROUTER}.create_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.post("/reviews", json=payload)
        assert resp.status_code == 201

    def test_missing_receiver_id_returns_422(self, client):
        bad = {k: v for k, v in self.VALID.items() if k != "receiver_id"}
        resp = client.post("/reviews", json=bad)
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# PUT /reviews/{id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateReviewRoute:
    def test_200_on_valid_comment_update(self, client):
        with patch(f"{_ROUTER}.update_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.put(f"/reviews/{uuid.uuid4()}", json={"comment": "Updated valid comment text here"})
        assert resp.status_code == 200

    def test_empty_body_returns_422(self, client):
        resp = client.put(f"/reviews/{uuid.uuid4()}", json={})
        assert resp.status_code == 422

    def test_404_for_missing_review(self, client):
        with patch(f"{_ROUTER}.update_review", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Not found")
            resp = client.put(f"/reviews/{uuid.uuid4()}", json={"comment": "Updated comment that is valid"})
        assert resp.status_code == 404

    def test_invalid_uuid_path_returns_422(self, client):
        resp = client.put("/reviews/not-a-uuid", json={"comment": "Valid updated comment here"})
        assert resp.status_code == 422

    def test_update_categories_triggers_service(self, client):
        new_cats = [str(uuid.uuid4()), str(uuid.uuid4())]
        with patch(f"{_ROUTER}.update_review", new_callable=AsyncMock) as m:
            m.return_value = _serialised_review()
            resp = client.put(f"/reviews/{uuid.uuid4()}", json={"category_ids": new_cats})
        assert resp.status_code == 200
        m.assert_awaited_once()

    def test_duplicate_category_ids_returns_422(self, client):
        same = str(uuid.uuid4())
        resp = client.put(f"/reviews/{uuid.uuid4()}", json={"category_ids": [same, same]})
        assert resp.status_code == 422

    def test_comment_too_short_returns_422(self, client):
        resp = client.put(f"/reviews/{uuid.uuid4()}", json={"comment": "tiny"})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Internal router
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def internal_client():
    a = FastAPI()
    a.include_router(internal_router)
    return TestClient(a, raise_server_exceptions=False)


class TestInternalRouter:
    def test_review_stats_200(self, internal_client):
        stats = {"reviews_total": 5, "reviews_this_month": 2, "reviews_last_month": 3}
        with patch.object(svc, "get_review_stats_internal", new_callable=AsyncMock, return_value=stats):
            resp = internal_client.get(f"/internal/reviews/stats?employee_id={make_uuid()}")
        assert resp.status_code == 200
        assert resp.json()["reviews_total"] == 5

    def test_review_stats_missing_param_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/stats")
        assert resp.status_code == 422

    def test_review_stats_batch_200(self, internal_client):
        eid1, eid2 = make_uuid(), make_uuid()
        batch = {
            eid1: {"reviews_total": 3, "reviews_this_month": 1, "reviews_last_month": 2},
            eid2: {"reviews_total": 0, "reviews_this_month": 0, "reviews_last_month": 0},
        }
        with patch.object(svc, "get_review_stats_batch_internal", new_callable=AsyncMock, return_value=batch):
            resp = internal_client.get(f"/internal/reviews/stats/batch?employee_ids={eid1},{eid2}")
        assert resp.status_code == 200
        assert eid1 in resp.json()

    def test_review_stats_batch_missing_param_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/stats/batch")
        assert resp.status_code == 422

    def test_recent_reviews_200(self, internal_client):
        with patch.object(svc, "get_recent_reviews_internal", new_callable=AsyncMock, return_value=[]):
            resp = internal_client.get(f"/internal/reviews/recent?employee_id={make_uuid()}")
        assert resp.status_code == 200

    def test_recent_reviews_missing_employee_id_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/recent")
        assert resp.status_code == 422

    def test_recent_reviews_limit_too_large_returns_422(self, internal_client):
        resp = internal_client.get(f"/internal/reviews/recent?employee_id={make_uuid()}&limit=999")
        assert resp.status_code == 422

    def test_recent_reviews_limit_zero_returns_422(self, internal_client):
        resp = internal_client.get(f"/internal/reviews/recent?employee_id={make_uuid()}&limit=0")
        assert resp.status_code == 422

    def test_trend_default_range_200(self, internal_client):
        with patch.object(svc, "get_recognition_trend_internal", new_callable=AsyncMock, return_value=[]):
            resp = internal_client.get("/internal/reviews/trend")
        assert resp.status_code == 200

    def test_trend_3m_200(self, internal_client):
        with patch.object(svc, "get_recognition_trend_internal", new_callable=AsyncMock, return_value=[]):
            resp = internal_client.get("/internal/reviews/trend?range=3m")
        assert resp.status_code == 200

    def test_trend_6m_200(self, internal_client):
        with patch.object(svc, "get_recognition_trend_internal", new_callable=AsyncMock, return_value=[]):
            resp = internal_client.get("/internal/reviews/trend?range=6m")
        assert resp.status_code == 200

    def test_trend_1y_200(self, internal_client):
        with patch.object(svc, "get_recognition_trend_internal", new_callable=AsyncMock, return_value=[]):
            resp = internal_client.get("/internal/reviews/trend?range=1y")
        assert resp.status_code == 200

    def test_trend_invalid_range_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/trend?range=99y")
        assert resp.status_code == 422

    def test_by_user_default_200(self, internal_client):
        data = {"items": [], "total": 0, "page": 1, "limit": 20, "pages": 0}
        with patch.object(svc, "get_recognition_by_user_internal", new_callable=AsyncMock, return_value=data):
            resp = internal_client.get("/internal/reviews/by-user")
        assert resp.status_code == 200

    def test_by_user_all_ranges(self, internal_client):
        data = {"items": [], "total": 0, "page": 1, "limit": 20, "pages": 0}
        for r in ("week", "month", "quarter", "year"):
            with patch.object(svc, "get_recognition_by_user_internal", new_callable=AsyncMock, return_value=data):
                resp = internal_client.get(f"/internal/reviews/by-user?range={r}")
            assert resp.status_code == 200

    def test_by_user_invalid_range_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/by-user?range=decade")
        assert resp.status_code == 422

    def test_by_team_default_200(self, internal_client):
        data = {"items": [], "total": 0, "page": 1, "limit": 10, "pages": 0}
        with patch.object(svc, "get_recognition_by_team_internal", new_callable=AsyncMock, return_value=data):
            resp = internal_client.get("/internal/reviews/by-team")
        assert resp.status_code == 200

    def test_by_team_invalid_range_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/by-team?range=decade")
        assert resp.status_code == 422

    def test_participation_200(self, internal_client):
        data = {
            "pie": [{"name": "Active", "value": 75.0}],
            "stats": {
                "total_employees": 10, "active_participants": 7,
                "non_participants": 3, "participation_rate": 70.0,
                "avg_reviews_per_employee": 2.5, "avg_reviews_last_month": 1.2,
            },
            "by_department": [],
        }
        with patch.object(svc, "get_participation_internal", new_callable=AsyncMock, return_value=data):
            resp = internal_client.get("/internal/reviews/participation")
        assert resp.status_code == 200

    def test_by_team_limit_out_of_range_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/by-team?limit=999")
        assert resp.status_code == 422

    def test_by_user_limit_out_of_range_returns_422(self, internal_client):
        resp = internal_client.get("/internal/reviews/by-user?limit=9999")
        assert resp.status_code == 422
