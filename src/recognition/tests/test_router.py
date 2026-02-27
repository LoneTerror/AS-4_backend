"""
test_router.py
Unit tests for src/recognition/router.py

Uses FastAPI TestClient with all auth dependencies overridden so no
real token validation or DB calls happen. Tests routing, HTTP methods,
query/path param validation, response codes, and service error propagation.
"""

import os
import sys
import types
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---------------------------------------------------------------------------
# Stub src.* namespace
# ---------------------------------------------------------------------------
for _p in [
    "src", "src.prisma", "src.prisma.client",
    "src.recognition", "src.recognition.dependencies",
    "src.recognition.schemas", "src.recognition.service",
    "src.common", "src.common.middleware",
]:
    sys.modules.setdefault(_p, types.ModuleType(_p))

from pydantic import BaseModel
from typing import List

class CurrentUser(BaseModel):
    id: str
    email: str
    roles: List[str]
    department_id: str | None = None

DEFAULT_USER = CurrentUser(id="user-1", email="u@test.com", roles=["EMPLOYEE"])

# ---------------------------------------------------------------------------
# Load real schemas
# ---------------------------------------------------------------------------
import importlib.util, pathlib

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_root    = pathlib.Path(__file__).parent.parent
_schemas = _load("schemas_mod", _root / "schemas.py")

sys.modules["src.recognition.schemas"].ReviewCreateRequest      = _schemas.ReviewCreateRequest
sys.modules["src.recognition.schemas"].ReviewUpdateRequest      = _schemas.ReviewUpdateRequest
sys.modules["src.recognition.schemas"].ReviewResponse           = _schemas.ReviewResponse
sys.modules["src.recognition.schemas"].PaginatedReviewResponse  = _schemas.PaginatedReviewResponse
sys.modules["src.recognition.dependencies"].CurrentUser         = CurrentUser

# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------
_service = MagicMock()
sys.modules["src.recognition.service"].RecognitionService = _service

# ---------------------------------------------------------------------------
# Stub get_current_user / require_roles so router imports stubs
# ---------------------------------------------------------------------------
async def _stub_get_current_user():
    return DEFAULT_USER

def _stub_require_roles(*args, **kwargs):
    async def _inner():
        return DEFAULT_USER
    return _inner

sys.modules["src.recognition.dependencies"].get_current_user = _stub_get_current_user
sys.modules["src.recognition.dependencies"].require_roles    = _stub_require_roles

# ---------------------------------------------------------------------------
# Load real router AFTER stubs are in place
# ---------------------------------------------------------------------------
_router_mod = _load("router_mod", _root / "router.py")

# ---------------------------------------------------------------------------
# Build FastAPI app and override ALL dependencies
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(_router_mod.router, prefix="/v1")

# Override the stubs that the router captured at import time
app.dependency_overrides[_router_mod.get_current_user] = lambda: DEFAULT_USER

# Override every require_roles-produced dependency registered on routes
for _route in app.routes:
    for _dep in getattr(_route, "dependencies", []):
        app.dependency_overrides[_dep.dependency] = lambda: DEFAULT_USER

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Sample data builders
# ---------------------------------------------------------------------------

def _review_json(**kw):
    base = dict(
        review_id=str(uuid4()),
        reviewer_id=str(uuid4()),
        receiver_id=str(uuid4()),
        rating=4,
        comment="Good work done here",
        image_url=None,
        video_url=None,
        status_id=str(uuid4()),
        review_at=datetime.now(timezone.utc).isoformat(),
        created_at=datetime.now(timezone.utc).isoformat(),
        created_by=str(uuid4()),
        updated_at=datetime.now(timezone.utc).isoformat(),
        updated_by=str(uuid4()),
    )
    base.update(kw)
    return base


def _paginated_json(items=None):
    return {
        "data": items or [_review_json()],
        "pagination": {
            "current_page": 1,
            "per_page": 20,
            "total": 1,
            "total_pages": 1,
            "has_next": False,
            "has_previous": False,
        }
    }


# ===========================================================================
# LIST REVIEWS  GET /v1/reviews
# ===========================================================================

class TestListReviewsRoute:

    def test_get_reviews_returns_200(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        resp = client.get("/v1/reviews")
        assert resp.status_code == 200

    def test_get_reviews_default_pagination_params(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        client.get("/v1/reviews")
        _service.list_reviews.assert_called_once()
        args = _service.list_reviews.call_args[0]
        assert args[0] == 1    # page default
        assert args[1] == 20   # page_size default

    def test_get_reviews_custom_pagination(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        client.get("/v1/reviews?page=3&page_size=10")
        args = _service.list_reviews.call_args[0]
        assert args[0] == 3
        assert args[1] == 10

    def test_page_less_than_1_returns_422(self):
        resp = client.get("/v1/reviews?page=0")
        assert resp.status_code == 422

    def test_page_size_less_than_1_returns_422(self):
        resp = client.get("/v1/reviews?page_size=0")
        assert resp.status_code == 422

    def test_page_size_more_than_100_returns_422(self):
        resp = client.get("/v1/reviews?page_size=101")
        assert resp.status_code == 422

    def test_page_size_exactly_100_accepted(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        resp = client.get("/v1/reviews?page_size=100")
        assert resp.status_code == 200

    def test_response_contains_data_and_pagination(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        resp = client.get("/v1/reviews")
        body = resp.json()
        assert "data"       in body
        assert "pagination" in body

    def test_get_not_405(self):
        _service.list_reviews = AsyncMock(return_value=_paginated_json())
        resp = client.get("/v1/reviews")
        assert resp.status_code != 405


# ===========================================================================
# GET REVIEW  GET /v1/reviews/{id}
# ===========================================================================

class TestGetReviewRoute:

    def test_get_review_by_valid_uuid_returns_200(self):
        uid = str(uuid4())
        _service.get_review = AsyncMock(return_value=_review_json(review_id=uid))
        resp = client.get(f"/v1/reviews/{uid}")
        assert resp.status_code == 200

    def test_get_review_invalid_uuid_returns_422(self):
        resp = client.get("/v1/reviews/not-a-uuid")
        assert resp.status_code == 422

    def test_get_review_passes_id_as_string(self):
        uid = str(uuid4())
        _service.get_review = AsyncMock(return_value=_review_json())
        client.get(f"/v1/reviews/{uid}")
        args = _service.get_review.call_args[0]
        assert args[0] == uid

    def test_get_review_service_404_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.get_review = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Review not found")
        )
        resp = client.get(f"/v1/reviews/{uid}")
        assert resp.status_code == 404

    def test_get_review_service_403_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.get_review = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Access denied")
        )
        resp = client.get(f"/v1/reviews/{uid}")
        assert resp.status_code == 403


# ===========================================================================
# CREATE REVIEW  POST /v1/reviews
# ===========================================================================

class TestCreateReviewRoute:

    def _valid_body(self, **kw):
        base = dict(
            receiver_id=str(uuid4()),
            rating=4,
            comment="Outstanding performance throughout the quarter.",
        )
        base.update(kw)
        return base

    def test_create_review_returns_201(self):
        _service.create_review = AsyncMock(return_value=_review_json())
        resp = client.post("/v1/reviews", json=self._valid_body())
        assert resp.status_code == 201

    def test_create_review_missing_rating_returns_422(self):
        resp = client.post("/v1/reviews", json=dict(
            receiver_id=str(uuid4()),
            comment="This is a valid comment length.",
        ))
        assert resp.status_code == 422

    def test_create_review_missing_comment_returns_422(self):
        resp = client.post("/v1/reviews", json=dict(
            receiver_id=str(uuid4()),
            rating=3,
        ))
        assert resp.status_code == 422

    def test_create_review_missing_receiver_id_returns_422(self):
        resp = client.post("/v1/reviews", json=dict(
            rating=3,
            comment="This is a valid comment length.",
        ))
        assert resp.status_code == 422

    def test_create_review_rating_out_of_range_returns_422(self):
        resp = client.post("/v1/reviews", json=self._valid_body(rating=6))
        assert resp.status_code == 422

    def test_create_review_comment_too_short_returns_422(self):
        resp = client.post("/v1/reviews", json=self._valid_body(comment="short"))
        assert resp.status_code == 422

    def test_create_review_extra_field_returns_422(self):
        resp = client.post("/v1/reviews", json={**self._valid_body(), "evil_field": "x"})
        assert resp.status_code == 422

    def test_create_review_service_422_propagates(self):
        from fastapi import HTTPException
        _service.create_review = AsyncMock(
            side_effect=HTTPException(status_code=422, detail="Self review not allowed")
        )
        resp = client.post("/v1/reviews", json=self._valid_body())
        assert resp.status_code == 422

    def test_create_review_with_image_url(self):
        _service.create_review = AsyncMock(return_value=_review_json())
        resp = client.post("/v1/reviews", json=self._valid_body(
            image_url="https://cdn.example.com/img.jpg"
        ))
        assert resp.status_code == 201

    def test_create_review_payload_forwarded_to_service(self):
        _service.create_review = AsyncMock(return_value=_review_json())
        client.post("/v1/reviews", json=self._valid_body())
        assert _service.create_review.called


# ===========================================================================
# UPDATE REVIEW  PUT /v1/reviews/{id}
# ===========================================================================

class TestUpdateReviewRoute:

    def test_update_review_returns_200(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        resp = client.put(f"/v1/reviews/{uid}", json={"rating": 5})
        assert resp.status_code == 200

    def test_update_review_invalid_uuid_returns_422(self):
        resp = client.put("/v1/reviews/not-a-uuid", json={"rating": 5})
        assert resp.status_code == 422

    def test_update_review_empty_body_returns_422(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}", json={})
        assert resp.status_code == 422

    def test_update_review_passes_id_as_string_to_service(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        client.put(f"/v1/reviews/{uid}", json={"rating": 3})
        args = _service.update_review.call_args[0]
        assert args[0] == uid

    def test_update_review_rating_out_of_range_returns_422(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}", json={"rating": 10})
        assert resp.status_code == 422

    def test_update_review_service_403_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.update_review = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not allowed")
        )
        resp = client.put(f"/v1/reviews/{uid}", json={"rating": 3})
        assert resp.status_code == 403

    def test_update_review_service_404_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.update_review = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Review not found")
        )
        resp = client.put(f"/v1/reviews/{uid}", json={"rating": 3})
        assert resp.status_code == 404

    def test_update_review_comment_only_accepted(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        resp = client.put(f"/v1/reviews/{uid}",
                          json={"comment": "Updated comment text length ok"})
        assert resp.status_code == 200

    def test_update_review_extra_field_rejected(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}", json={"rating": 3, "hack": "x"})
        assert resp.status_code == 422


# ===========================================================================
# Router config sanity checks
# ===========================================================================

class TestRouterConfig:

    def _routes_map(self):
        """Build {path: set(methods)} — merges multiple routes on same path."""
        result = {}
        for r in app.routes:
            path    = getattr(r, "path",    None)
            methods = getattr(r, "methods", None)
            if path and methods:
                result.setdefault(path, set()).update(methods)
        return result

    def test_router_prefix_is_reviews(self):
        assert _router_mod.router.prefix == "/reviews"

    def test_list_route_exists(self):
        routes = self._routes_map()
        assert "/v1/reviews" in routes
        assert "GET" in routes["/v1/reviews"]

    def test_create_route_exists(self):
        routes = self._routes_map()
        assert "/v1/reviews" in routes
        assert "POST" in routes["/v1/reviews"]

    def test_get_by_id_route_exists(self):
        routes = self._routes_map()
        assert "/v1/reviews/{id}" in routes
        assert "GET" in routes["/v1/reviews/{id}"]

    def test_update_route_exists(self):
        routes = self._routes_map()
        assert "/v1/reviews/{id}" in routes
        assert "PUT" in routes["/v1/reviews/{id}"]