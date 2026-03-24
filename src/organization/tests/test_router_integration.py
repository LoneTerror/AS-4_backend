"""
src/organization/tests/test_router_integration.py
──────────────────────────────────────────────────
Integration tests for src/organization/router.py endpoints.

KEY: router.py imports via `from src.organization import service` (module-level)
so patches target `src.organization.service.<fn>` directly.

check_route_permission is overridden via FastAPI dependency_overrides.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import src.common.dependencies as deps
from src.organization.router import (
    departments_router,
    designations_router,
    department_types_router,
    statuses_router,
    audit_logs_router,
)
from conftest import (
    _fake_audit_log,
    _fake_department,
    _fake_dept_type,
    _fake_designation,
    _fake_status,
    make_uuid,
    utcnow,
)

_SVC = "src.organization.service"
NOW  = utcnow()


# ─────────────────────────────────────────────────────────────────────────────
# App + fixture helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI(root_path="/v1/organizations")
    app.include_router(departments_router,      prefix="/departments")
    app.include_router(designations_router,     prefix="/designations")
    app.include_router(department_types_router, prefix="/department-types")
    app.include_router(statuses_router,         prefix="/statuses")
    app.include_router(audit_logs_router,       prefix="/audit-logs")
    return app


def _override_auth(app: FastAPI, roles=None):
    user = deps.CurrentUser(id=make_uuid(), email="admin@test.com", roles=roles or ["SUPER_ADMIN"])
    async def _no_auth():
        return user
    app.dependency_overrides[deps.check_route_permission] = _no_auth
    return user


@pytest.fixture
def app():
    a = _make_app()
    _override_auth(a)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ─── serialiser helpers ────────────────────────────────────────────────────────

def _paginated(items=None):
    from src.organization.schemas import PaginationMeta
    items = items or []
    return {
        "data": items,
        "pagination": PaginationMeta(
            current_page=1, per_page=20, total=len(items),
            total_pages=1 if items else 0,
            has_next=False, has_previous=False,
        ),
    }


def _dept_list_response(depts=None):
    from src.organization.schemas import DepartmentListResponse, PaginationMeta
    depts = depts or []
    return DepartmentListResponse(
        data=depts,
        pagination=PaginationMeta(
            current_page=1, per_page=20, total=len(depts),
            total_pages=1 if depts else 0,
            has_next=False, has_previous=False,
        ),
    )


def _desig_list_response(desigs=None):
    from src.organization.schemas import DesignationListResponse, PaginationMeta
    desigs = desigs or []
    return DesignationListResponse(
        data=desigs,
        pagination=PaginationMeta(
            current_page=1, per_page=20, total=len(desigs),
            total_pages=1 if desigs else 0,
            has_next=False, has_previous=False,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /departments
# ─────────────────────────────────────────────────────────────────────────────

class TestListDepartmentsRoute:
    def test_200_response(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            resp = client.get("/departments")
        assert resp.status_code == 200

    def test_response_has_data_key(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            resp = client.get("/departments")
        assert "data" in resp.json()

    def test_response_has_pagination_key(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            resp = client.get("/departments")
        assert "pagination" in resp.json()

    def test_default_page_1(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments")
        assert m.call_args.args[0] == 1

    def test_default_limit_20(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments")
        assert m.call_args.args[1] == 20

    def test_page_param_passed(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments?page=3")
        assert m.call_args.args[0] == 3

    def test_limit_param_passed(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments?limit=50")
        assert m.call_args.args[1] == 50

    def test_is_active_filter_passed(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments?is_active=true")
        assert m.call_args.args[2] is True

    def test_search_param_passed(self, client):
        with patch(f"{_SVC}.list_departments", new_callable=AsyncMock) as m:
            m.return_value = _dept_list_response()
            client.get("/departments?search=eng")
        assert m.call_args.args[3] == "eng"

    def test_page_less_than_1_returns_422(self, client):
        resp = client.get("/departments?page=0")
        assert resp.status_code == 422

    def test_limit_greater_than_100_returns_422(self, client):
        resp = client.get("/departments?limit=101")
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /departments/{department_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDepartmentRoute:
    def test_200_response(self, client):
        from src.organization.schemas import DepartmentDetailResponse
        dept_id = str(uuid.uuid4())
        mock_resp = DepartmentDetailResponse(
            department_id=uuid.UUID(dept_id), department_name="Eng",
            department_code="ENG", employee_count=3,
            is_active=True, created_at=NOW,
        )
        with patch(f"{_SVC}.get_department_detail", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            resp = client.get(f"/departments/{dept_id}")
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.get_department_detail", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Department not found")
            resp = client.get(f"/departments/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_service_called_with_dept_id(self, client):
        from src.organization.schemas import DepartmentDetailResponse
        dept_id = str(uuid.uuid4())
        mock_resp = DepartmentDetailResponse(
            department_id=uuid.UUID(dept_id), department_name="Eng",
            department_code="ENG", employee_count=0,
            is_active=True, created_at=NOW,
        )
        with patch(f"{_SVC}.get_department_detail", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            client.get(f"/departments/{dept_id}")
        m.assert_awaited_once_with(dept_id)

    def test_response_has_employee_count(self, client):
        from src.organization.schemas import DepartmentDetailResponse
        dept_id = str(uuid.uuid4())
        mock_resp = DepartmentDetailResponse(
            department_id=uuid.UUID(dept_id), department_name="Eng",
            department_code="ENG", employee_count=7,
            is_active=True, created_at=NOW,
        )
        with patch(f"{_SVC}.get_department_detail", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            resp = client.get(f"/departments/{dept_id}")
        assert resp.json()["employee_count"] == 7


# ─────────────────────────────────────────────────────────────────────────────
# POST /departments
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateDepartmentRoute:
    def _valid_payload(self):
        return {
            "department_name":    "Finance",
            "department_code":    "FIN",
            "department_type_id": str(uuid.uuid4()),
        }

    def _mock_created(self):
        from src.organization.schemas import DepartmentCreatedResponse
        return DepartmentCreatedResponse(
            department_id=uuid.uuid4(), department_name="Finance",
            department_code="FIN", is_active=True, created_at=NOW,
        )

    def test_201_response(self, client):
        with patch(f"{_SVC}.create_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            resp = client.post("/departments", json=self._valid_payload())
        assert resp.status_code == 201

    def test_response_has_department_id(self, client):
        with patch(f"{_SVC}.create_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            resp = client.post("/departments", json=self._valid_payload())
        assert "department_id" in resp.json()

    def test_400_on_duplicate(self, client):
        with patch(f"{_SVC}.create_department", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="already exists")
            resp = client.post("/departments", json=self._valid_payload())
        assert resp.status_code == 400

    def test_missing_name_returns_422(self, client):
        payload = self._valid_payload()
        del payload["department_name"]
        resp = client.post("/departments", json=payload)
        assert resp.status_code == 422

    def test_missing_type_id_returns_422(self, client):
        payload = self._valid_payload()
        del payload["department_type_id"]
        resp = client.post("/departments", json=payload)
        assert resp.status_code == 422

    def test_invalid_uuid_type_id_returns_422(self, client):
        payload = self._valid_payload()
        payload["department_type_id"] = "not-a-uuid"
        resp = client.post("/departments", json=payload)
        assert resp.status_code == 422

    def test_code_uppercased_by_schema(self, client):
        with patch(f"{_SVC}.create_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            client.post("/departments", json={**self._valid_payload(), "department_code": "fin"})
        payload_received = m.call_args.args[0]
        assert payload_received.department_code == "FIN"

    def test_service_called_with_user_id(self, client):
        with patch(f"{_SVC}.create_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            client.post("/departments", json=self._valid_payload())
        assert m.call_args.args[1] is not None


# ─────────────────────────────────────────────────────────────────────────────
# PUT /departments/{department_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDepartmentRoute:
    def _mock_updated(self):
        from src.organization.schemas import DepartmentUpdatedResponse
        return DepartmentUpdatedResponse(
            department_id=uuid.uuid4(), department_name="Updated",
            department_code="UPD", is_active=True, updated_at=NOW,
        )

    def test_200_response(self, client):
        dept_id = str(uuid.uuid4())
        with patch(f"{_SVC}.update_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            resp = client.put(f"/departments/{dept_id}", json={"department_name": "Updated"})
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.update_department", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="not found")
            resp = client.put(f"/departments/{uuid.uuid4()}", json={"department_name": "X"})
        assert resp.status_code == 404

    def test_400_on_no_valid_fields(self, client):
        with patch(f"{_SVC}.update_department", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="No valid fields")
            resp = client.put(f"/departments/{uuid.uuid4()}", json={"is_active": False})
        assert resp.status_code == 400

    def test_service_called_with_dept_id(self, client):
        dept_id = str(uuid.uuid4())
        with patch(f"{_SVC}.update_department", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            client.put(f"/departments/{dept_id}", json={"department_name": "X"})
        assert m.call_args.args[0] == dept_id


# ─────────────────────────────────────────────────────────────────────────────
# GET /department-types
# ─────────────────────────────────────────────────────────────────────────────

class TestDepartmentTypesRoute:
    def test_200_response(self, client):
        with patch(f"{_SVC}.list_department_types", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/department-types")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        from src.organization.schemas import DepartmentTypeResponse
        t = DepartmentTypeResponse(
            department_type_id=uuid.uuid4(), type_name="Engineering", type_code="ENG"
        )
        with patch(f"{_SVC}.list_department_types", new_callable=AsyncMock) as m:
            m.return_value = [t]
            resp = client.get("/department-types")
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 1

    def test_empty_list_returns_200(self, client):
        with patch(f"{_SVC}.list_department_types", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/department-types")
        assert resp.json() == []


# ─────────────────────────────────────────────────────────────────────────────
# GET /designations
# ─────────────────────────────────────────────────────────────────────────────

class TestListDesignationsRoute:
    def test_200_response(self, client):
        with patch(f"{_SVC}.list_designations", new_callable=AsyncMock) as m:
            m.return_value = _desig_list_response()
            resp = client.get("/designations")
        assert resp.status_code == 200

    def test_default_page_1(self, client):
        with patch(f"{_SVC}.list_designations", new_callable=AsyncMock) as m:
            m.return_value = _desig_list_response()
            client.get("/designations")
        assert m.call_args.args[0] == 1

    def test_is_active_filter_passed(self, client):
        with patch(f"{_SVC}.list_designations", new_callable=AsyncMock) as m:
            m.return_value = _desig_list_response()
            client.get("/designations?is_active=false")
        assert m.call_args.args[2] is False

    def test_page_0_returns_422(self, client):
        resp = client.get("/designations?page=0")
        assert resp.status_code == 422

    def test_limit_gt_100_returns_422(self, client):
        resp = client.get("/designations?limit=101")
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /designations/{designation_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetDesignationRoute:
    def test_200_response(self, client):
        from src.organization.schemas import DesignationDetailResponse
        did = str(uuid.uuid4())
        mock_resp = DesignationDetailResponse(
            designation_id=uuid.UUID(did), designation_name="Engineer",
            designation_code="SWE", level=3, employee_count=5,
            is_active=True, created_at=NOW,
        )
        with patch(f"{_SVC}.get_designation_detail", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            resp = client.get(f"/designations/{did}")
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.get_designation_detail", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Designation not found")
            resp = client.get(f"/designations/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_response_has_level(self, client):
        from src.organization.schemas import DesignationDetailResponse
        did = str(uuid.uuid4())
        mock_resp = DesignationDetailResponse(
            designation_id=uuid.UUID(did), designation_name="Engineer",
            designation_code="SWE", level=4, employee_count=0,
            is_active=True, created_at=NOW,
        )
        with patch(f"{_SVC}.get_designation_detail", new_callable=AsyncMock) as m:
            m.return_value = mock_resp
            resp = client.get(f"/designations/{did}")
        assert resp.json()["level"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# POST /designations
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateDesignationRoute:
    def _valid_payload(self):
        return {"designation_name": "Lead Engineer", "designation_code": "LE", "level": 5}

    def _mock_created(self):
        from src.organization.schemas import DesignationListItem
        return DesignationListItem(
            designation_id=uuid.uuid4(), designation_name="Lead Engineer",
            designation_code="LE", level=5, is_active=True, created_at=NOW,
        )

    def test_201_response(self, client):
        with patch(f"{_SVC}.create_designation", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            resp = client.post("/designations", json=self._valid_payload())
        assert resp.status_code == 201

    def test_400_on_duplicate(self, client):
        with patch(f"{_SVC}.create_designation", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="already exists")
            resp = client.post("/designations", json=self._valid_payload())
        assert resp.status_code == 400

    def test_missing_level_returns_422(self, client):
        resp = client.post("/designations", json={"designation_name": "X", "designation_code": "X"})
        assert resp.status_code == 422

    def test_level_zero_returns_422(self, client):
        resp = client.post("/designations", json={**self._valid_payload(), "level": 0})
        assert resp.status_code == 422

    def test_code_uppercased_by_schema(self, client):
        with patch(f"{_SVC}.create_designation", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            client.post("/designations", json={**self._valid_payload(), "designation_code": "le"})
        assert m.call_args.args[0].designation_code == "LE"


# ─────────────────────────────────────────────────────────────────────────────
# PUT /designations/{designation_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDesignationRoute:
    def _mock_updated(self):
        from src.organization.schemas import DesignationDetailResponse
        return DesignationDetailResponse(
            designation_id=uuid.uuid4(), designation_name="Senior Engineer",
            designation_code="SWE3", level=5, employee_count=0,
            is_active=True, created_at=NOW,
        )

    def test_200_response(self, client):
        did = str(uuid.uuid4())
        with patch(f"{_SVC}.update_designation", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            resp = client.put(f"/designations/{did}", json={"designation_name": "Senior"})
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.update_designation", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="not found")
            resp = client.put(f"/designations/{uuid.uuid4()}", json={"designation_name": "X"})
        assert resp.status_code == 404

    def test_service_called_with_id(self, client):
        did = str(uuid.uuid4())
        with patch(f"{_SVC}.update_designation", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            client.put(f"/designations/{did}", json={"designation_name": "X"})
        assert m.call_args.args[0] == did


# ─────────────────────────────────────────────────────────────────────────────
# GET /statuses
# ─────────────────────────────────────────────────────────────────────────────

class TestListStatusesRoute:
    def test_200_response(self, client):
        with patch(f"{_SVC}.list_statuses", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/statuses")
        assert resp.status_code == 200

    def test_entity_type_filter_passed(self, client):
        with patch(f"{_SVC}.list_statuses", new_callable=AsyncMock) as m:
            m.return_value = []
            client.get("/statuses?entity_type=REVIEW")
        m.assert_awaited_once_with("REVIEW")

    def test_returns_list(self, client):
        from src.organization.schemas import StatusResponse
        st = StatusResponse(
            status_id=uuid.uuid4(), status_code="ACTIVE",
            status_name="Active", entity_type="EMPLOYEE", created_at=NOW,
        )
        with patch(f"{_SVC}.list_statuses", new_callable=AsyncMock) as m:
            m.return_value = [st]
            resp = client.get("/statuses")
        assert isinstance(resp.json(), list)


# ─────────────────────────────────────────────────────────────────────────────
# GET /statuses/{status_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetStatusRoute:
    def _mock_detail(self):
        from src.organization.schemas import StatusDetailResponse
        return StatusDetailResponse(
            status_id=uuid.uuid4(), status_code="ACTIVE",
            status_name="Active", entity_type="EMPLOYEE", created_at=NOW,
        )

    def test_200_response(self, client):
        with patch(f"{_SVC}.get_status", new_callable=AsyncMock) as m:
            m.return_value = self._mock_detail()
            resp = client.get(f"/statuses/{uuid.uuid4()}")
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.get_status", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="not found")
            resp = client.get(f"/statuses/{uuid.uuid4()}")
        assert resp.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# POST /statuses
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateStatusRoute:
    def _valid_payload(self):
        return {"status_code": "ON_LEAVE", "status_name": "On Leave", "entity_type": "EMPLOYEE"}

    def _mock_created(self):
        from src.organization.schemas import StatusDetailResponse
        return StatusDetailResponse(
            status_id=uuid.uuid4(), status_code="ON_LEAVE",
            status_name="On Leave", entity_type="EMPLOYEE", created_at=NOW,
        )

    def test_201_response(self, client):
        with patch(f"{_SVC}.create_status", new_callable=AsyncMock) as m:
            m.return_value = self._mock_created()
            resp = client.post("/statuses", json=self._valid_payload())
        assert resp.status_code == 201

    def test_409_on_duplicate(self, client):
        with patch(f"{_SVC}.create_status", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="CONFLICT")
            resp = client.post("/statuses", json=self._valid_payload())
        assert resp.status_code == 409

    def test_invalid_entity_type_returns_422(self, client):
        resp = client.post("/statuses", json={
            "status_code": "X", "status_name": "X", "entity_type": "INVALID"
        })
        assert resp.status_code == 422

    def test_missing_status_code_returns_422(self, client):
        resp = client.post("/statuses", json={"status_name": "X", "entity_type": "EMPLOYEE"})
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# PUT /statuses/{status_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateStatusRoute:
    def _mock_updated(self):
        from src.organization.schemas import StatusDetailResponse
        return StatusDetailResponse(
            status_id=uuid.uuid4(), status_code="ACTIVE",
            status_name="Updated Name", entity_type="EMPLOYEE", created_at=NOW,
        )

    def test_200_response(self, client):
        with patch(f"{_SVC}.update_status", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            resp = client.put(f"/statuses/{uuid.uuid4()}", json={"status_name": "Updated"})
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.update_status", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="not found")
            resp = client.put(f"/statuses/{uuid.uuid4()}", json={"status_name": "X"})
        assert resp.status_code == 404

    def test_service_receives_status_id(self, client):
        sid = str(uuid.uuid4())
        with patch(f"{_SVC}.update_status", new_callable=AsyncMock) as m:
            m.return_value = self._mock_updated()
            client.put(f"/statuses/{sid}", json={"status_name": "X"})
        assert m.call_args.args[0] == sid


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit-logs
# ─────────────────────────────────────────────────────────────────────────────

class TestListAuditLogsRoute:
    def _mock_result(self):
        from src.organization.schemas import PaginationMeta
        return {
            "data": [],
            "pagination": PaginationMeta(
                current_page=1, per_page=50, total=0,
                total_pages=0, has_next=False, has_previous=False,
            ),
        }

    def test_200_response(self, client):
        with patch(f"{_SVC}.list_audit_logs", new_callable=AsyncMock) as m:
            m.return_value = self._mock_result()
            resp = client.get("/audit-logs")
        assert resp.status_code == 200

    def test_response_has_data_and_pagination(self, client):
        with patch(f"{_SVC}.list_audit_logs", new_callable=AsyncMock) as m:
            m.return_value = self._mock_result()
            resp = client.get("/audit-logs")
        body = resp.json()
        assert "data" in body
        assert "pagination" in body

    def test_default_limit_50(self, client):
        with patch(f"{_SVC}.list_audit_logs", new_callable=AsyncMock) as m:
            m.return_value = self._mock_result()
            client.get("/audit-logs")
        assert m.call_args.args[1] == 50

    def test_table_name_filter_passed(self, client):
        with patch(f"{_SVC}.list_audit_logs", new_callable=AsyncMock) as m:
            m.return_value = self._mock_result()
            client.get("/audit-logs?table_name=departments")
        assert m.call_args.args[2] == "departments"

    def test_limit_gt_200_returns_422(self, client):
        resp = client.get("/audit-logs?limit=201")
        assert resp.status_code == 422

    def test_page_0_returns_422(self, client):
        resp = client.get("/audit-logs?page=0")
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# GET /audit-logs/{audit_id}
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAuditLogRoute:
    def _mock_log(self):
        from src.organization.schemas import AuditLogResponse
        return AuditLogResponse(
            audit_id=uuid.uuid4(), table_name="departments",
            record_id=uuid.uuid4(), operation_type="INSERT",
            performed_by=uuid.uuid4(), performed_at=NOW,
        )

    def test_200_response(self, client):
        with patch(f"{_SVC}.get_audit_log", new_callable=AsyncMock) as m:
            m.return_value = self._mock_log()
            resp = client.get(f"/audit-logs/{uuid.uuid4()}")
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_SVC}.get_audit_log", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="not found")
            resp = client.get(f"/audit-logs/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_service_called_with_audit_id(self, client):
        aid = str(uuid.uuid4())
        with patch(f"{_SVC}.get_audit_log", new_callable=AsyncMock) as m:
            m.return_value = self._mock_log()
            client.get(f"/audit-logs/{aid}")
        m.assert_awaited_once_with(aid)

    def test_response_has_table_name(self, client):
        with patch(f"{_SVC}.get_audit_log", new_callable=AsyncMock) as m:
            m.return_value = self._mock_log()
            resp = client.get(f"/audit-logs/{uuid.uuid4()}")
        assert "table_name" in resp.json()
