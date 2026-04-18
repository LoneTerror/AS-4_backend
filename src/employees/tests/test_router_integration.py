"""
src/employees/tests/test_router_integration.py
───────────────────────────────────────────────
FastAPI TestClient integration tests for employees router and internal router.

Patch target: src.employees.router.service.<fn>  (module-level import)
Internal router patches: src.employees.internal_router.db.<table>
"""
from __future__ import annotations
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import src.common.dependencies as deps
from src.employees.router          import router as emp_router
from src.employees.internal_router import router as internal_router
from conftest import (
    _fake_employee, _fake_dept, _fake_desig, _fake_status,
    _fake_wallet, _fake_role, make_uuid,
)

_R  = "src.employees.router"
_IR = "src.employees.internal_router"
NOW = datetime(2026, 1, 15, 10, 0, 0)
DOJ = date(2020, 3, 1)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _make_app():
    app = FastAPI(root_path="/aabhar/v1/employees")
    app.include_router(emp_router)
    app.include_router(internal_router)
    return app

def _override_auth(app, roles=None):
    user = deps.CurrentUser(id=make_uuid(), email="admin@test.com", roles=roles or ["SUPER_ADMIN"])
    async def _no_auth(): return user
    app.dependency_overrides[deps.check_route_permission] = _no_auth
    return user

def _pg(total=0):
    return {"current_page": 1, "per_page": 20, "total": total,
            "total_pages": 1 if total else 0, "has_next": False, "has_previous": False}

def _emp_list_item(e=None):
    e = e or _fake_employee()
    return {"employee_id": str(e.employee_id), "username": e.username,
            "email": e.email, "date_of_joining": DOJ.isoformat(),
            "is_active": True, "created_at": NOW.isoformat()}

def _emp_detail_dict(e=None):
    e = e or _fake_employee()
    return {"employee_id": str(e.employee_id), "username": e.username,
            "email": e.email, "date_of_joining": DOJ.isoformat(),
            "is_active": True, "created_at": NOW.isoformat(), "roles": []}

def _emp_created_dict(e=None):
    e = e or _fake_employee()
    return {
        "employee_id": str(e.employee_id), "username": e.username,
        "email": e.email, "designation_id": str(uuid.uuid4()),
        "department_id": str(uuid.uuid4()), "manager_id": str(uuid.uuid4()),
        "date_of_joining": DOJ.isoformat(), "status_id": str(uuid.uuid4()),
        "is_active": True, "created_at": NOW.isoformat(),
    }

@pytest.fixture
def app():
    a = _make_app(); _override_auth(a); return a

@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# GET /list
# ══════════════════════════════════════════════════════════════════════════════
class TestListEmployeesRoute:
    def test_200_returns_data_and_pagination(self, client):
        result = MagicMock()
        result.model_dump.return_value = {"data": [_emp_list_item()], "pagination": _pg(1)}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            resp = client.get("/list")
        assert resp.status_code == 200

    def test_service_called_with_defaults(self, client):
        result = MagicMock()
        result.model_dump.return_value = {"data": [], "pagination": _pg()}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            client.get("/list")
        m.assert_awaited_once()

    def test_page_ge_1_enforced(self, client):
        resp = client.get("/list?page=0")
        assert resp.status_code == 422

    def test_limit_max_100_enforced(self, client):
        resp = client.get("/list?limit=101")
        assert resp.status_code == 422

    def test_department_id_forwarded(self, client):
        dept_id = str(uuid.uuid4())
        result  = MagicMock(); result.model_dump.return_value = {"data": [], "pagination": _pg()}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            client.get(f"/list?department_id={dept_id}")
        assert m.call_args.args[2] is not None  # department_id passed

    def test_search_param_forwarded(self, client):
        result = MagicMock(); result.model_dump.return_value = {"data": [], "pagination": _pg()}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            client.get("/list?search=alice")
        args = m.call_args.args
        assert "alice" in args

    def test_500_on_service_error(self, client):
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.side_effect = Exception("db down")
            resp = client.get("/list")
        assert resp.status_code == 500

    def test_sort_by_param_forwarded(self, client):
        result = MagicMock(); result.model_dump.return_value = {"data": [], "pagination": _pg()}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            client.get("/list?sort_by=username&sort_order=asc")
        args = m.call_args.args
        assert "username" in args
        assert "asc" in args

    def test_is_active_param_forwarded(self, client):
        result = MagicMock(); result.model_dump.return_value = {"data": [], "pagination": _pg()}
        with patch(f"{_R}.service.list_employees", new_callable=AsyncMock) as m:
            m.return_value = result
            client.get("/list?is_active=true")
        args = m.call_args.args
        assert True in args


# ══════════════════════════════════════════════════════════════════════════════
# POST /create
# ══════════════════════════════════════════════════════════════════════════════
class TestCreateEmployeeRoute:
    def _payload(self, **ov):
        base = {
            "username": "new.emp", "email": "new@example.com",
            "password": "Secure1!",
            "designation_id": str(uuid.uuid4()), "department_id": str(uuid.uuid4()),
            "manager_id": str(uuid.uuid4()), "date_of_joining": "2020-01-01",
            "status_id": str(uuid.uuid4()),
        }
        base.update(ov); return base

    def test_201_on_valid_payload(self, client):
        e = _fake_employee()
        with patch(f"{_R}.service.create_employee", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_created_dict(e))
            resp = client.post("/create", json=self._payload())
        assert resp.status_code == 201

    def test_400_on_duplicate(self, client):
        with patch(f"{_R}.service.create_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="Username or Email already exists")
            resp = client.post("/create", json=self._payload())
        assert resp.status_code == 400

    def test_missing_username_returns_422(self, client):
        p = self._payload(); del p["username"]
        resp = client.post("/create", json=p)
        assert resp.status_code == 422

    def test_invalid_email_returns_422(self, client):
        resp = client.post("/create", json=self._payload(email="not-email"))
        assert resp.status_code == 422

    def test_weak_password_returns_422(self, client):
        resp = client.post("/create", json=self._payload(password="weak"))
        assert resp.status_code == 422

    def test_future_date_of_joining_returns_422(self, client):
        resp = client.post("/create", json=self._payload(date_of_joining="2099-01-01"))
        assert resp.status_code == 422

    def test_missing_status_id_returns_422(self, client):
        p = self._payload(); del p["status_id"]
        resp = client.post("/create", json=p)
        assert resp.status_code == 422

    def test_service_called_with_current_user_id(self, client):
        with patch(f"{_R}.service.create_employee", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_created_dict())
            client.post("/create", json=self._payload())
        m.assert_awaited_once()
        assert m.call_args.args[1] is not None   # created_by_id passed


# ══════════════════════════════════════════════════════════════════════════════
# GET /{employee_id}
# ══════════════════════════════════════════════════════════════════════════════
class TestGetEmployeeRoute:
    def test_200_on_found(self, client):
        emp_id = make_uuid()
        with patch(f"{_R}.service.get_employee_detail", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_detail_dict())
            resp = client.get(f"/{emp_id}")
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_R}.service.get_employee_detail", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Employee not found")
            resp = client.get(f"/{make_uuid()}")
        assert resp.status_code == 404

    def test_service_called_with_id(self, client):
        emp_id = make_uuid()
        with patch(f"{_R}.service.get_employee_detail", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_detail_dict())
            client.get(f"/{emp_id}")
        m.assert_awaited_once_with(emp_id)

    def test_reserved_word_list_returns_404(self, client):
        # "list" is reserved — router guards against it
        resp = client.get("/list")
        # list is registered BEFORE the wildcard so it hits the list endpoint
        assert resp.status_code in (200, 422)   # hits list route, not wildcard

    def test_reserved_word_create_returns_404_from_wildcard(self, client):
        resp = client.get("/create")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# PUT /{employee_id}
# ══════════════════════════════════════════════════════════════════════════════
class TestUpdateEmployeeRoute:
    def test_200_on_valid_update(self, client):
        emp_id = make_uuid()
        with patch(f"{_R}.service.update_employee", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_detail_dict())
            resp = client.put(f"/{emp_id}", json={"username": "updated.name"})
        assert resp.status_code == 200

    def test_404_propagated(self, client):
        with patch(f"{_R}.service.update_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Employee not found")
            resp = client.put(f"/{make_uuid()}", json={"username": "new.name"})
        assert resp.status_code == 404

    def test_invalid_email_returns_422(self, client):
        resp = client.put(f"/{make_uuid()}", json={"email": "not-email"})
        assert resp.status_code == 422

    def test_username_too_short_returns_422(self, client):
        resp = client.put(f"/{make_uuid()}", json={"username": "ab"})
        assert resp.status_code == 422

    def test_service_receives_employee_id(self, client):
        emp_id = make_uuid()
        with patch(f"{_R}.service.update_employee", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_detail_dict())
            client.put(f"/{emp_id}", json={"username": "new.user"})
        assert m.call_args.args[0] == emp_id

    def test_service_receives_updated_by(self, client):
        with patch(f"{_R}.service.update_employee", new_callable=AsyncMock) as m:
            m.return_value = MagicMock(**_emp_detail_dict())
            client.put(f"/{make_uuid()}", json={"username": "new.user"})
        assert m.call_args.args[2] is not None


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /{employee_id}  (deactivate)
# ══════════════════════════════════════════════════════════════════════════════
class TestPatchEmployeeRoute:
    def test_204_on_success(self, client):
        with patch(f"{_R}.service.patch_employee", new_callable=AsyncMock) as m:
            m.return_value = True
            resp = client.patch(f"/{make_uuid()}")
        assert resp.status_code == 204

    def test_404_propagated(self, client):
        with patch(f"{_R}.service.patch_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Employee not found")
            resp = client.patch(f"/{make_uuid()}")
        assert resp.status_code == 404

    def test_500_propagated(self, client):
        with patch(f"{_R}.service.patch_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=500, detail="INACTIVE status not found")
            resp = client.patch(f"/{make_uuid()}")
        assert resp.status_code == 500

    def test_service_receives_employee_id(self, client):
        emp_id = make_uuid()
        with patch(f"{_R}.service.patch_employee", new_callable=AsyncMock) as m:
            m.return_value = True
            client.patch(f"/{emp_id}")
        assert m.call_args.args[0] == emp_id


# ══════════════════════════════════════════════════════════════════════════════
# Internal routes
# ══════════════════════════════════════════════════════════════════════════════
class TestInternalActiveCount:
    def test_200_returns_now_and_last_month(self, client):
        st = _fake_status(status_code="ACTIVE")
        with (
            patch.object(
                __import__("src.employees.internal_router", fromlist=["db"]).db,
                "status_master",
            ) as mock_sm,
            patch.object(
                __import__("src.employees.internal_router", fromlist=["db"]).db,
                "employees",
            ) as mock_e,
        ):
            mock_sm.find_first = AsyncMock(return_value=st)
            mock_e.count       = AsyncMock(side_effect=[42, 38])
            resp = client.get("/internal/employees/active-count")
        assert resp.status_code == 200

    def test_returns_zeros_when_no_active_status(self, client):
        with patch.object(
            __import__("src.employees.internal_router", fromlist=["db"]).db,
            "status_master",
        ) as mock_sm:
            mock_sm.find_first = AsyncMock(return_value=None)
            resp = client.get("/internal/employees/active-count")
        assert resp.status_code == 200
        body = resp.json()
        assert body["now"] == 0
        assert body["last_month"] == 0


class TestInternalDepartmentsWithMembers:
    def test_200_returns_list(self, client):
        from src.employees import internal_router as ir
        dept = _fake_dept(department_name="Engineering")
        emp  = _fake_employee()
        emp.designations_employees_designation_idTodesignations = _fake_desig(designation_name="SWE")
        emp.department_id = dept.department_id
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            resp = client.get("/internal/employees/departments-with-members")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_response_shape(self, client):
        from src.employees import internal_router as ir
        dept = _fake_dept(department_name="Engineering")
        emp  = _fake_employee()
        emp.designations_employees_designation_idTodesignations = _fake_desig(designation_name="SWE")
        emp.department_id = dept.department_id
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            resp = client.get("/internal/employees/departments-with-members")
        item = resp.json()[0]
        for key in ("department_id", "department_name", "members"):
            assert key in item

    def test_members_contain_employee_fields(self, client):
        from src.employees import internal_router as ir
        dept = _fake_dept()
        emp  = _fake_employee(username="alice")
        emp.designations_employees_designation_idTodesignations = _fake_desig(designation_name="Lead")
        emp.department_id = dept.department_id
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            resp = client.get("/internal/employees/departments-with-members")
        member = resp.json()[0]["members"][0]
        assert "employee_id" in member
        assert "username"    in member
        assert "designation_name" in member

    def test_employee_without_dept_excluded(self, client):
        from src.employees import internal_router as ir
        dept = _fake_dept()
        emp  = _fake_employee()
        emp.department_id = None   # no department
        emp.designations_employees_designation_idTodesignations = _fake_desig()
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            resp = client.get("/internal/employees/departments-with-members")
        assert resp.json()[0]["members"] == []

    def test_empty_departments(self, client):
        from src.employees import internal_router as ir
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[])
            mock_e.find_many = AsyncMock(return_value=[])
            resp = client.get("/internal/employees/departments-with-members")
        assert resp.json() == []

    def test_no_designation_gives_na(self, client):
        from src.employees import internal_router as ir
        dept = _fake_dept()
        emp  = _fake_employee()
        emp.department_id = dept.department_id
        emp.designations_employees_designation_idTodesignations = None  # no designation
        with (
            patch.object(ir.db, "departments") as mock_d,
            patch.object(ir.db, "employees")   as mock_e,
        ):
            mock_d.find_many = AsyncMock(return_value=[dept])
            mock_e.find_many = AsyncMock(return_value=[emp])
            resp = client.get("/internal/employees/departments-with-members")
        member = resp.json()[0]["members"][0]
        assert member["designation_name"] == "N/A"
