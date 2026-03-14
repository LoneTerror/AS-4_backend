"""
test_router.py
Unit tests for src/recognition/router.py

UPDATED:
- Removed 'rating' field from all request and response mocks as it was replaced 
  by multi-category support (category_ids / category_tags).
- _valid_body() now uses category_ids (plural list) matching the real
  ReviewCreateRequest schema.
- Removed quarters_elapsed / apply_decay stubs — they don't exist in
  points_engine.py.
- Added stubs for ReviewCategoryCreateRequest and ReviewCategoryUpdateRequest
  so router.py can be imported.
- test_create_review_missing_category_ids_returns_422 replaces the old
  singular category_id version.
- test_create_review_invalid_category_id_uuid_returns_422 updated to use
  category_ids list with an invalid UUID element.
- test_update_review_category_ids_only_accepted replaces singular version.
- test_update_review_invalid_category_ids_returns_422 updated similarly.
"""

import os
import sys
import types
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from src.common.dependencies import get_current_user, check_route_permission

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

sys.modules["src.prisma.client"] = MagicMock()
for _p in [
    "src.prisma", "src.prisma.client",
    "src.recognition.dependencies",
    "src.recognition.schemas",
    "src.recognition.points_engine",
    "src.common.middleware",
    "src.common.dependencies"
]:
    sys.modules.setdefault(_p, types.ModuleType(_p))

# Load the REAL points_engine.
import pathlib as _pathlib_pe
_pe_mod_path = _pathlib_pe.Path(__file__).parent.parent / "points_engine.py"
import importlib.util as _ilu_pe
_pe_mod_spec = _ilu_pe.spec_from_file_location("_real_pe_router", _pe_mod_path)
_real_pe_mod = _ilu_pe.module_from_spec(_pe_mod_spec)
_pe_mod_spec.loader.exec_module(_real_pe_mod)
_pe_mod = sys.modules["src.recognition.points_engine"]
_pe_mod.calculate_points = _real_pe_mod.calculate_points
_pe_mod.PointsResult     = _real_pe_mod.PointsResult

from pydantic import BaseModel
from typing import List, Optional

class CurrentUser(BaseModel):
    id: str
    email: str
    roles: List[str]
    department_id: str | None = None

DEFAULT_USER = CurrentUser(id="user-1", email="u@test.com", roles=["EMPLOYEE"])

# ---------------------------------------------------------------------------
# Load real schemas and wire into stub namespace
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

# Stub category schemas if not present in schemas.py
from pydantic import BaseModel as _BM
from typing import List as _List, Optional as _Opt

_ReviewCategoryResponse = getattr(_schemas, "ReviewCategoryResponse", None)
if _ReviewCategoryResponse is None:
    class _ReviewCategoryResponse(_BM):
        category_id:   object
        category_code: str
        multiplier:    float = 1.0
        is_active:     bool  = True

_PaginatedReviewCategoryResponse = getattr(_schemas, "PaginatedReviewCategoryResponse", None)
if _PaginatedReviewCategoryResponse is None:
    class _PaginatedReviewCategoryResponse(_BM):
        data:       _List[_ReviewCategoryResponse] = []
        pagination: dict = {}

_ReviewCategoryCreateRequest = getattr(_schemas, "ReviewCategoryCreateRequest", None)
if _ReviewCategoryCreateRequest is None:
    class _ReviewCategoryCreateRequest(_BM):
        category_code: str
        category_name: str
        multiplier:    float
        description:   _Opt[str] = None

_ReviewCategoryUpdateRequest = getattr(_schemas, "ReviewCategoryUpdateRequest", None)
if _ReviewCategoryUpdateRequest is None:
    class _ReviewCategoryUpdateRequest(_BM):
        category_code: _Opt[str]   = None
        category_name: _Opt[str]   = None
        multiplier:    _Opt[float] = None
        description:   _Opt[str]  = None
        is_active:     _Opt[bool]  = None

sys.modules["src.recognition.schemas"].ReviewCategoryResponse           = _ReviewCategoryResponse
sys.modules["src.recognition.schemas"].PaginatedReviewCategoryResponse  = _PaginatedReviewCategoryResponse
sys.modules["src.recognition.schemas"].ReviewCategoryCreateRequest      = _ReviewCategoryCreateRequest
sys.modules["src.recognition.schemas"].ReviewCategoryUpdateRequest      = _ReviewCategoryUpdateRequest
sys.modules["src.recognition.dependencies"].CurrentUser                 = CurrentUser
sys.modules["src.common.dependencies"].CurrentUser                      = CurrentUser 

# Now it is safe to import your project modules
from src.recognition.service import RecognitionService

# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------
_service = MagicMock()

# ---------------------------------------------------------------------------
# Stub auth dependencies
# ---------------------------------------------------------------------------
async def _stub_get_current_user():
    return DEFAULT_USER

async def _stub_require_roles():
    return DEFAULT_USER

async def _stub_check_route_permission():
    return DEFAULT_USER

sys.modules["src.recognition.dependencies"].get_current_user = _stub_get_current_user
sys.modules["src.recognition.dependencies"].require_roles    = _stub_require_roles

sys.modules["src.common.dependencies"].check_route_permission = _stub_check_route_permission
sys.modules["src.common.dependencies"].get_current_user = _stub_get_current_user

# ---------------------------------------------------------------------------
# Load real router AFTER stubs are in place
# ---------------------------------------------------------------------------
_router_mod = _load("router_mod", _root / "router.py")
_router_mod.RecognitionService = _service

# ---------------------------------------------------------------------------
# Build FastAPI app and override ALL dependencies
# ---------------------------------------------------------------------------
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(_router_mod.router, prefix="/v1")

for _route in app.routes:
    for _dep in getattr(_route, "dependencies", []):
        app.dependency_overrides[_dep.dependency] = lambda: DEFAULT_USER

app.dependency_overrides[get_current_user] = lambda: DEFAULT_USER
app.dependency_overrides[check_route_permission] = lambda: DEFAULT_USER
client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Sample data builders
# ---------------------------------------------------------------------------

def _review_json(**kw):
    base = dict(
        review_id=str(uuid4()),
        reviewer_id=str(uuid4()),
        receiver_id=str(uuid4()),
        comment="Good work done here",
        image_url=None,
        video_url=None,
        status_id=str(uuid4()),
        review_at=datetime.now(timezone.utc).isoformat(),
        created_at=datetime.now(timezone.utc).isoformat(),
        created_by=str(uuid4()),
        updated_at=datetime.now(timezone.utc).isoformat(),
        updated_by=str(uuid4()),
        category_tags=[],
        category_ids=[],
        category_codes=[],
        raw_points=None,
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
            "has_previous": False
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
        _service.get_review = AsyncMock(return_value=_review_json())
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
        """
        FIXED: The real ReviewCreateRequest uses category_ids: List[UUID]
        (plural list).
        """
        base = dict(
            receiver_id=str(uuid4()),
            category_ids=[str(uuid4())],
            comment="Outstanding performance throughout the quarter.",
        )
        base.update(kw)
        return base

    def test_create_review_returns_201(self):
        _service.create_review = AsyncMock(return_value=_review_json())
        resp = client.post("/v1/reviews", json=self._valid_body())
        assert resp.status_code == 201

    def test_create_review_missing_comment_returns_422(self):
        body = self._valid_body()
        del body["comment"]
        resp = client.post("/v1/reviews", json=body)
        assert resp.status_code == 422

    def test_create_review_missing_receiver_id_returns_422(self):
        body = self._valid_body()
        del body["receiver_id"]
        resp = client.post("/v1/reviews", json=body)
        assert resp.status_code == 422

    def test_create_review_missing_category_ids_returns_422(self):
        body = self._valid_body()
        del body["category_ids"]
        resp = client.post("/v1/reviews", json=body)
        assert resp.status_code == 422

    def test_create_review_empty_category_ids_returns_422(self):
        """An empty list violates min_length=1 on category_ids."""
        resp = client.post("/v1/reviews", json=self._valid_body(category_ids=[]))
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

    def test_create_review_invalid_category_id_in_list_returns_422(self):
        resp = client.post("/v1/reviews", json=self._valid_body(
            category_ids=["not-a-uuid"]
        ))
        assert resp.status_code == 422

    def test_create_review_too_many_category_ids_returns_422(self):
        """More than 5 category IDs should fail max_length validation."""
        resp = client.post("/v1/reviews", json=self._valid_body(
            category_ids=[str(uuid4()) for _ in range(6)]
        ))
        assert resp.status_code == 422


# ===========================================================================
# UPDATE REVIEW  PUT /v1/reviews/{id}
# ===========================================================================

class TestUpdateReviewRoute:

    def test_update_review_returns_200(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        resp = client.put(f"/v1/reviews/{uid}", json={"comment": "New valid comment length"})
        assert resp.status_code == 200

    def test_update_review_invalid_uuid_returns_422(self):
        resp = client.put("/v1/reviews/not-a-uuid", json={"comment": "Valid length comment"})
        assert resp.status_code == 422

    def test_update_review_empty_body_returns_422(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}", json={})
        assert resp.status_code == 422

    def test_update_review_passes_id_as_string_to_service(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        client.put(f"/v1/reviews/{uid}", json={"comment": "Valid length comment"})
        args = _service.update_review.call_args[0]
        assert args[0] == uid

    def test_update_review_service_403_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.update_review = AsyncMock(
            side_effect=HTTPException(status_code=403, detail="Not allowed")
        )
        resp = client.put(f"/v1/reviews/{uid}", json={"comment": "Valid length comment"})
        assert resp.status_code == 403

    def test_update_review_service_404_propagates(self):
        from fastapi import HTTPException
        uid = str(uuid4())
        _service.update_review = AsyncMock(
            side_effect=HTTPException(status_code=404, detail="Review not found")
        )
        resp = client.put(f"/v1/reviews/{uid}", json={"comment": "Valid length comment"})
        assert resp.status_code == 404

    def test_update_review_comment_only_accepted(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        resp = client.put(f"/v1/reviews/{uid}",
                          json={"comment": "Updated comment text length ok"})
        assert resp.status_code == 200

    def test_update_review_extra_field_rejected(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}", json={"comment": "Valid length comment", "hack": "x"})
        assert resp.status_code == 422

    def test_update_review_category_ids_only_accepted(self):
        uid = str(uuid4())
        _service.update_review = AsyncMock(return_value=_review_json())
        resp = client.put(f"/v1/reviews/{uid}",
                          json={"category_ids": [str(uuid4())]})
        assert resp.status_code == 200

    def test_update_review_invalid_category_ids_returns_422(self):
        uid = str(uuid4())
        resp = client.put(f"/v1/reviews/{uid}",
                          json={"category_ids": ["bad-uuid"]})
        assert resp.status_code == 422


# ===========================================================================
# Router config sanity checks
# ===========================================================================

class TestRouterConfig:

    def _routes_map(self):
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
