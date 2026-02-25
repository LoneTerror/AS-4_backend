"""
Tests for src/organization/router.py
Covers: all department and designation endpoints via TestClient,
        require_roles helper, department types dropdown
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.organization import schemas
from src.organization.dependencies import get_current_employee, CurrentEmployee


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now().isoformat()
DEPT_ID = str(uuid4())
DESIG_ID = str(uuid4())
DEPT_TYPE_ID = str(uuid4())


def _mock_employee(roles=None):
    return CurrentEmployee(
        id="emp-1",
        roles=roles or ["HR_ADMIN"],
        email="emp@x.com",
    )


def _create_test_app(employee: CurrentEmployee):
    """Create app with get_current_employee overridden to return the given employee."""
    from src.organization.router import departments_router, designations_router, department_types_router

    app = FastAPI()
    app.include_router(departments_router, prefix="/v1/org/departments")
    app.include_router(designations_router, prefix="/v1/org/designations")
    app.include_router(department_types_router, prefix="/v1/org/department-types")

    # Override auth dependency — bypasses all OAuth2/JWT checks
    app.dependency_overrides[get_current_employee] = lambda: employee

    return app


def _dept_list_response():
    return schemas.DepartmentListResponse(
        data=[
            schemas.DepartmentListItem(
                department_id=uuid4(),
                department_name="Engineering",
                department_code="ENG",
                is_active=True,
                created_at=datetime.now(),
            )
        ],
        pagination=schemas.PaginationMeta(
            current_page=1, per_page=20, total=1,
            total_pages=1, has_next=False, has_previous=False,
        ),
    )


def _desig_list_response():
    return schemas.DesignationListResponse(
        data=[
            schemas.DesignationListItem(
                designation_id=uuid4(),
                designation_name="Engineer",
                designation_code="ENG",
                level=3,
                is_active=True,
                created_at=datetime.now(),
            )
        ],
        pagination=schemas.PaginationMeta(
            current_page=1, per_page=20, total=1,
            total_pages=1, has_next=False, has_previous=False,
        ),
    )


# ---------------------------------------------------------------------------
# require_roles helper (unit tests — no HTTP)
# ---------------------------------------------------------------------------

class TestRequireRolesHelper:

    def test_allowed_role_passes(self):
        from src.organization.router import require_roles
        emp = CurrentEmployee(id="u1", roles=["HR_ADMIN"], email="u@x.com")
        require_roles(emp, ["HR_ADMIN", "SUPER_ADMIN"])  # should not raise

    def test_disallowed_role_raises_403(self):
        from src.organization.router import require_roles
        from fastapi import HTTPException
        emp = CurrentEmployee(id="u1", roles=["EMPLOYEE"], email="u@x.com")

        with pytest.raises(HTTPException) as exc:
            require_roles(emp, ["HR_ADMIN"])

        assert exc.value.status_code == 403

    def test_role_comparison_is_case_insensitive(self):
        from src.organization.router import require_roles
        emp = CurrentEmployee(id="u1", roles=["hr_admin"], email="u@x.com")
        require_roles(emp, ["HR_ADMIN"])  # should not raise

    def test_multiple_roles_any_match_passes(self):
        from src.organization.router import require_roles
        emp = CurrentEmployee(id="u1", roles=["MANAGER", "EMPLOYEE"], email="u@x.com")
        require_roles(emp, ["MANAGER"])


# ---------------------------------------------------------------------------
# Unauthenticated fixture (no override → real OAuth2 kicks in → 401)
# ---------------------------------------------------------------------------

@pytest.fixture
def unauthed_client():
    from src.organization.router import departments_router, designations_router, department_types_router
    app = FastAPI()
    app.include_router(departments_router, prefix="/v1/org/departments")
    app.include_router(designations_router, prefix="/v1/org/designations")
    app.include_router(department_types_router, prefix="/v1/org/department-types")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Department endpoints
# ---------------------------------------------------------------------------

class TestListDepartments:

    def test_returns_department_list(self):
        emp = _mock_employee(roles=["EMPLOYEE"])
        app = _create_test_app(emp)

        with (
            patch("src.organization.service.list_departments", new=AsyncMock(return_value=_dept_list_response())),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/v1/org/departments")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/v1/org/departments")
        assert resp.status_code == 401

    def test_pagination_params_forwarded(self):
        emp = _mock_employee()
        app = _create_test_app(emp)

        with patch("src.organization.service.list_departments", new=AsyncMock(return_value=_dept_list_response())) as mock_svc:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.get("/v1/org/departments?page=2&limit=10")

        mock_svc.assert_called_once_with(2, 10, None, None)


class TestGetDepartment:

    def test_returns_department_detail(self):
        emp = _mock_employee()
        app = _create_test_app(emp)

        detail = schemas.DepartmentDetailResponse(
            department_id=uuid4(),
            department_name="Engineering",
            department_code="ENG",
            employee_count=5,
            is_active=True,
            created_at=datetime.now(),
        )

        with patch("src.organization.service.get_department_detail", new=AsyncMock(return_value=detail)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(f"/v1/org/departments/{DEPT_ID}")

        assert resp.status_code == 200
        assert resp.json()["department_code"] == "ENG"

    def test_not_found_returns_404(self):
        from fastapi import HTTPException
        emp = _mock_employee()
        app = _create_test_app(emp)

        with patch(
            "src.organization.service.get_department_detail",
            new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Not found")),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/v1/org/departments/bad-id")

        assert resp.status_code == 404


class TestCreateDepartment:

    def _payload(self):
        return {
            "department_name": "Finance",
            "department_code": "FIN",
            "department_type_id": str(uuid4()),
        }

    def test_hr_admin_can_create(self):
        emp = _mock_employee(roles=["HR_ADMIN"])
        app = _create_test_app(emp)

        created = schemas.DepartmentCreatedResponse(
            department_id=uuid4(),
            department_name="Finance",
            department_code="FIN",
            is_active=True,
            created_at=datetime.now(),
        )

        with patch("src.organization.service.create_department", new=AsyncMock(return_value=created)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post("/v1/org/departments", json=self._payload())

        assert resp.status_code == 201

    def test_employee_role_cannot_create(self):
        emp = _mock_employee(roles=["EMPLOYEE"])
        app = _create_test_app(emp)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post("/v1/org/departments", json=self._payload())

        assert resp.status_code == 403


class TestUpdateDepartment:

    def test_updates_successfully(self):
        emp = _mock_employee(roles=["SUPER_ADMIN"])
        app = _create_test_app(emp)

        updated = schemas.DepartmentUpdatedResponse(
            department_id=uuid4(),
            department_name="Updated",
            department_code="UPD",
            is_active=True,
            updated_at=datetime.now(),
        )

        with patch("src.organization.service.update_department", new=AsyncMock(return_value=updated)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.put(f"/v1/org/departments/{DEPT_ID}", json={"department_name": "Updated"})

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Designation endpoints
# ---------------------------------------------------------------------------

class TestListDesignations:

    def test_returns_designation_list(self):
        emp = _mock_employee(roles=["EMPLOYEE"])
        app = _create_test_app(emp)

        with patch("src.organization.service.list_designations", new=AsyncMock(return_value=_desig_list_response())):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/v1/org/designations")

        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/v1/org/designations")
        assert resp.status_code == 401


class TestGetDesignation:

    def test_returns_designation_detail(self):
        emp = _mock_employee()
        app = _create_test_app(emp)

        detail = schemas.DesignationDetailResponse(
            designation_id=uuid4(),
            designation_name="Engineer",
            designation_code="ENG",
            level=3,
            employee_count=2,
            is_active=True,
            created_at=datetime.now(),
        )

        with patch("src.organization.service.get_designation_detail", new=AsyncMock(return_value=detail)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get(f"/v1/org/designations/{DESIG_ID}")

        assert resp.status_code == 200


class TestCreateDesignation:

    def test_hr_admin_can_create(self):
        emp = _mock_employee(roles=["HR_ADMIN"])
        app = _create_test_app(emp)

        created = schemas.DesignationListItem(
            designation_id=uuid4(),
            designation_name="Lead",
            designation_code="LEAD",
            level=5,
            is_active=True,
            created_at=datetime.now(),
        )

        with patch("src.organization.service.create_designation", new=AsyncMock(return_value=created)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/v1/org/designations",
                    json={"designation_name": "Lead", "designation_code": "LEAD", "level": 5},
                )

        assert resp.status_code == 201

    def test_employee_cannot_create(self):
        emp = _mock_employee(roles=["EMPLOYEE"])
        app = _create_test_app(emp)

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/v1/org/designations",
                json={"designation_name": "Lead", "designation_code": "LEAD", "level": 5},
            )

        assert resp.status_code == 403


class TestUpdateDesignation:

    def test_updates_successfully(self):
        emp = _mock_employee(roles=["HR_ADMIN"])
        app = _create_test_app(emp)

        updated = schemas.DesignationDetailResponse(
            designation_id=uuid4(),
            designation_name="Senior Lead",
            designation_code="SLEAD",
            level=6,
            employee_count=1,
            is_active=True,
            created_at=datetime.now(),
        )

        with patch("src.organization.service.update_designation", new=AsyncMock(return_value=updated)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.put(
                    f"/v1/org/designations/{DESIG_ID}",
                    json={"designation_name": "Senior Lead"},
                )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Department Types dropdown
# ---------------------------------------------------------------------------

class TestDepartmentTypesEndpoint:

    def test_returns_list_of_types(self):
        emp = _mock_employee(roles=["EMPLOYEE"])
        app = _create_test_app(emp)

        types = [
            schemas.DepartmentTypeResponse(
                department_type_id=uuid4(),
                type_name="Core",
                type_code="CORE",
            )
        ]

        with patch("src.organization.service.list_department_types", new=AsyncMock(return_value=types)):
            with TestClient(app, raise_server_exceptions=False) as client:
                resp = client.get("/v1/org/department-types")

        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["type_code"] == "CORE"

    def test_unauthenticated_returns_401(self, unauthed_client):
        resp = unauthed_client.get("/v1/org/department-types")
        assert resp.status_code == 401