"""
src/roles/tests/test_router_integration.py
────────────────────────────────────────────
FastAPI TestClient integration tests for src/roles/router.py.

Patch target: src.roles.router.service.<fn>
(router imports via `import src.roles.service as service`)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import src.common.dependencies as deps
from src.roles.router import router as roles_router
from conftest import (
    _fake_role, _fake_employee_role, _fake_route_permission,
    _current_user, make_uuid,
)

_R = "src.roles.router"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_app():
    app = FastAPI(root_path="/aabhar/v1/roles")
    app.include_router(roles_router)
    return app

def _override_auth(app, roles=None):
    user = deps.CurrentUser(
        id=make_uuid(), email="admin@test.com",
        roles=roles or ["SUPER_ADMIN"],
    )
    async def _no_auth(): return user
    app.dependency_overrides[deps.check_route_permission] = _no_auth
    return user

@pytest.fixture
def app():
    a = _make_app(); _override_auth(a); return a

@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ══════════════════════════════════════════════════════════════════════════════
# GET /list
# ══════════════════════════════════════════════════════════════════════════════

class TestListRolesRoute:
    def test_200_returns_list(self, client):
        roles = [{"role_id": make_uuid(), "role_code": "EMPLOYEE", "role_name": "Employee"}]
        with patch(f"{_R}.service.list_roles", new_callable=AsyncMock) as m:
            m.return_value = roles
            resp = client.get("/list")
        assert resp.status_code == 200

    def test_empty_list_ok(self, client):
        with patch(f"{_R}.service.list_roles", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/list")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_service_called_once(self, client):
        with patch(f"{_R}.service.list_roles", new_callable=AsyncMock) as m:
            m.return_value = []
            client.get("/list")
        m.assert_awaited_once()

    def test_500_on_service_error(self, client):
        with patch(f"{_R}.service.list_roles", new_callable=AsyncMock) as m:
            m.side_effect = Exception("db error")
            resp = client.get("/list")
        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /create
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateRoleRoute:
    def _payload(self, **ov):
        base = {"role_name": "HR Admin", "role_code": "HR_ADMIN"}
        base.update(ov); return base

    def test_201_on_valid_payload(self, client):
        role = _fake_role(role_code="HR_ADMIN")
        with patch(f"{_R}.service.create_role", new_callable=AsyncMock) as m:
            m.return_value = role
            resp = client.post("/create", json=self._payload())
        assert resp.status_code == 201

    def test_409_on_duplicate(self, client):
        with patch(f"{_R}.service.create_role", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="Role 'HR_ADMIN' already exists")
            resp = client.post("/create", json=self._payload())
        assert resp.status_code == 409

    def test_missing_role_name_returns_422(self, client):
        resp = client.post("/create", json={"role_code": "HR_ADMIN"})
        assert resp.status_code == 422

    def test_missing_role_code_returns_422(self, client):
        resp = client.post("/create", json={"role_name": "HR Admin"})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/create", json={})
        assert resp.status_code == 422

    def test_service_called_with_current_user(self, client):
        role = _fake_role()
        with patch(f"{_R}.service.create_role", new_callable=AsyncMock) as m:
            m.return_value = role
            client.post("/create", json=self._payload())
        # current_user is passed as second positional arg
        assert m.call_args.args[1] is not None

    def test_description_forwarded(self, client):
        role = _fake_role()
        with patch(f"{_R}.service.create_role", new_callable=AsyncMock) as m:
            m.return_value = role
            client.post("/create", json=self._payload(description="Admin role"))
        body_arg = m.call_args.args[0]
        assert body_arg.description == "Admin role"


# ══════════════════════════════════════════════════════════════════════════════
# GET /employees
# ══════════════════════════════════════════════════════════════════════════════

class TestListEmployeeRolesRoute:
    def test_200_returns_list(self, client):
        er = {"employee_role_id": make_uuid(), "employee": {}, "role": {}}
        with patch(f"{_R}.service.list_employee_roles", new_callable=AsyncMock) as m:
            m.return_value = [er]
            resp = client.get("/employees")
        assert resp.status_code == 200

    def test_empty_list_ok(self, client):
        with patch(f"{_R}.service.list_employee_roles", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/employees")
        assert resp.json() == []

    def test_service_called_once(self, client):
        with patch(f"{_R}.service.list_employee_roles", new_callable=AsyncMock) as m:
            m.return_value = []
            client.get("/employees")
        m.assert_awaited_once()

    def test_500_on_service_error(self, client):
        with patch(f"{_R}.service.list_employee_roles", new_callable=AsyncMock) as m:
            m.side_effect = Exception("db error")
            resp = client.get("/employees")
        assert resp.status_code == 500


# ══════════════════════════════════════════════════════════════════════════════
# POST /assign
# ══════════════════════════════════════════════════════════════════════════════

class TestAssignRoleRoute:
    def _payload(self, **ov):
        base = {"employee_id": make_uuid(), "role_id": make_uuid()}
        base.update(ov); return base

    def test_201_on_valid_payload(self, client):
        er = _fake_employee_role()
        with patch(f"{_R}.service.assign_role", new_callable=AsyncMock) as m:
            m.return_value = er
            resp = client.post("/assign", json=self._payload())
        assert resp.status_code == 201

    def test_409_on_duplicate(self, client):
        with patch(f"{_R}.service.assign_role", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="Employee already has this role")
            resp = client.post("/assign", json=self._payload())
        assert resp.status_code == 409

    def test_missing_employee_id_returns_422(self, client):
        resp = client.post("/assign", json={"role_id": make_uuid()})
        assert resp.status_code == 422

    def test_missing_role_id_returns_422(self, client):
        resp = client.post("/assign", json={"employee_id": make_uuid()})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/assign", json={})
        assert resp.status_code == 422

    def test_service_called_with_payload_and_user(self, client):
        eid = make_uuid(); rid = make_uuid()
        er  = _fake_employee_role()
        with patch(f"{_R}.service.assign_role", new_callable=AsyncMock) as m:
            m.return_value = er
            client.post("/assign", json={"employee_id": eid, "role_id": rid})
        body_arg = m.call_args.args[0]
        assert body_arg.employee_id == eid
        assert body_arg.role_id     == rid


# ══════════════════════════════════════════════════════════════════════════════
# POST /revoke
# ══════════════════════════════════════════════════════════════════════════════

class TestRevokeRoleRoute:
    def _payload(self, **ov):
        base = {"employee_id": make_uuid(), "role_id": make_uuid()}
        base.update(ov); return base

    def test_200_on_valid_revoke(self, client):
        er = _fake_employee_role()
        with patch(f"{_R}.service.revoke_role", new_callable=AsyncMock) as m:
            m.return_value = er
            resp = client.post("/revoke", json=self._payload())
        assert resp.status_code == 200

    def test_404_on_missing_assignment(self, client):
        with patch(f"{_R}.service.revoke_role", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Active role assignment not found")
            resp = client.post("/revoke", json=self._payload())
        assert resp.status_code == 404

    def test_missing_employee_id_returns_422(self, client):
        resp = client.post("/revoke", json={"role_id": make_uuid()})
        assert resp.status_code == 422

    def test_missing_role_id_returns_422(self, client):
        resp = client.post("/revoke", json={"employee_id": make_uuid()})
        assert resp.status_code == 422

    def test_service_called_with_correct_ids(self, client):
        eid = make_uuid(); rid = make_uuid()
        er  = _fake_employee_role()
        with patch(f"{_R}.service.revoke_role", new_callable=AsyncMock) as m:
            m.return_value = er
            client.post("/revoke", json={"employee_id": eid, "role_id": rid})
        body_arg = m.call_args.args[0]
        assert body_arg.employee_id == eid
        assert body_arg.role_id     == rid


# ══════════════════════════════════════════════════════════════════════════════
# GET /route-permissions
# ══════════════════════════════════════════════════════════════════════════════

class TestListRoutePermissionsRoute:
    def test_200_returns_list(self, client):
        perms = [{"route_key": "GET:/aabhar/v1/roles/list", "roles": []}]
        with patch(f"{_R}.service.list_route_permissions", new_callable=AsyncMock) as m:
            m.return_value = perms
            resp = client.get("/route-permissions")
        assert resp.status_code == 200

    def test_empty_list_ok(self, client):
        with patch(f"{_R}.service.list_route_permissions", new_callable=AsyncMock) as m:
            m.return_value = []
            resp = client.get("/route-permissions")
        assert resp.json() == []

    def test_service_called_once(self, client):
        with patch(f"{_R}.service.list_route_permissions", new_callable=AsyncMock) as m:
            m.return_value = []
            client.get("/route-permissions")
        m.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# POST /route-permissions
# ══════════════════════════════════════════════════════════════════════════════

class TestAddRoutePermissionRoute:
    def _payload(self, **ov):
        base = {"route_key": "GET:/aabhar/v1/roles/list", "role_id": make_uuid()}
        base.update(ov); return base

    def test_201_on_valid_payload(self, client):
        rp = _fake_route_permission()
        with patch(f"{_R}.service.add_route_permission", new_callable=AsyncMock) as m:
            m.return_value = rp
            resp = client.post("/route-permissions", json=self._payload())
        assert resp.status_code == 201

    def test_409_on_duplicate(self, client):
        with patch(f"{_R}.service.add_route_permission", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="Permission already exists")
            resp = client.post("/route-permissions", json=self._payload())
        assert resp.status_code == 409

    def test_missing_route_key_returns_422(self, client):
        resp = client.post("/route-permissions", json={"role_id": make_uuid()})
        assert resp.status_code == 422

    def test_missing_role_id_returns_422(self, client):
        resp = client.post("/route-permissions", json={"route_key": "GET:/aabhar/v1/x"})
        assert resp.status_code == 422

    def test_title_optional(self, client):
        rp = _fake_route_permission()
        with patch(f"{_R}.service.add_route_permission", new_callable=AsyncMock) as m:
            m.return_value = rp
            resp = client.post("/route-permissions", json=self._payload(title="My Route"))
        assert resp.status_code == 201

    def test_body_forwarded_correctly(self, client):
        rp = _fake_route_permission(); rid = make_uuid()
        with patch(f"{_R}.service.add_route_permission", new_callable=AsyncMock) as m:
            m.return_value = rp
            client.post("/route-permissions",
                        json={"route_key": "POST:/aabhar/v1/x", "role_id": rid, "title": "Test"})
        body_arg = m.call_args.args[0]
        assert body_arg.route_key == "POST:/aabhar/v1/x"
        assert body_arg.role_id   == rid
        assert body_arg.title     == "Test"


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /route-permissions
# ══════════════════════════════════════════════════════════════════════════════

class TestRemoveRoutePermissionRoute:
    def _payload(self, **ov):
        base = {"route_key": "GET:/aabhar/v1/roles/list", "role_id": make_uuid()}
        base.update(ov); return base

    def test_200_on_valid_remove(self, client):
        rp = _fake_route_permission()
        with patch(f"{_R}.service.remove_route_permission", new_callable=AsyncMock) as m:
            m.return_value = rp
            resp = client.patch("/route-permissions", json=self._payload())
        assert resp.status_code == 200

    def test_404_on_missing_permission(self, client):
        with patch(f"{_R}.service.remove_route_permission", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="Active permission not found")
            resp = client.patch("/route-permissions", json=self._payload())
        assert resp.status_code == 404

    def test_missing_route_key_returns_422(self, client):
        resp = client.patch("/route-permissions", json={"role_id": make_uuid()})
        assert resp.status_code == 422

    def test_missing_role_id_returns_422(self, client):
        resp = client.patch("/route-permissions", json={"route_key": "GET:/v1/x"})
        assert resp.status_code == 422

    def test_service_called_with_body(self, client):
        rid = make_uuid()
        rp  = _fake_route_permission()
        with patch(f"{_R}.service.remove_route_permission", new_callable=AsyncMock) as m:
            m.return_value = rp
            client.patch("/route-permissions",
                         json={"route_key": "GET:/aabhar/v1/roles/list", "role_id": rid})
        body_arg = m.call_args.args[0]
        assert body_arg.role_id == rid


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /route-permissions/title
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateRouteTitleRoute:
    def _payload(self, **ov):
        base = {"route_key": "GET:/aabhar/v1/roles/list", "title": "List All Roles"}
        base.update(ov); return base

    def test_200_on_valid_update(self, client):
        result = {"route_key": "GET:/aabhar/v1/roles/list", "title": "List All Roles", "updated_rows": 2}
        with patch(f"{_R}.service.update_route_title", new_callable=AsyncMock) as m:
            m.return_value = result
            resp = client.patch("/route-permissions/title", json=self._payload())
        assert resp.status_code == 200

    def test_404_when_route_key_not_found(self, client):
        with patch(f"{_R}.service.update_route_title", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=404, detail="No permissions found")
            resp = client.patch("/route-permissions/title", json=self._payload())
        assert resp.status_code == 404

    def test_missing_route_key_returns_422(self, client):
        resp = client.patch("/route-permissions/title", json={"title": "x"})
        assert resp.status_code == 422

    def test_missing_title_returns_422(self, client):
        resp = client.patch("/route-permissions/title", json={"route_key": "GET:/aabhar/v1/x"})
        assert resp.status_code == 422

    def test_response_contains_updated_rows(self, client):
        result = {"route_key": "GET:/aabhar/v1/x", "title": "New", "updated_rows": 3}
        with patch(f"{_R}.service.update_route_title", new_callable=AsyncMock) as m:
            m.return_value = result
            resp = client.patch("/route-permissions/title", json=self._payload())
        assert "updated_rows" in resp.json()

    def test_body_forwarded_correctly(self, client):
        result = {"route_key": "PATCH:/aabhar/v1/x", "title": "My Title", "updated_rows": 1}
        with patch(f"{_R}.service.update_route_title", new_callable=AsyncMock) as m:
            m.return_value = result
            client.patch("/route-permissions/title",
                         json={"route_key": "PATCH:/aabhar/v1/x", "title": "My Title"})
        body_arg = m.call_args.args[0]
        assert body_arg.route_key == "PATCH:/aabhar/v1/x"
        assert body_arg.title     == "My Title"
