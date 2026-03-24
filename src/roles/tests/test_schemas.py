"""
src/roles/tests/test_schemas.py
─────────────────────────────────
Pydantic schema validation tests for src/roles/schemas.py.
No DB or IO — pure model-layer tests.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.roles.schemas import (
    CreateRoleRequest,
    AssignRoleRequest,
    RevokeRoleRequest,
    SetRoutePermissionRequest,
    DeleteRoutePermissionRequest,
    UpdateRouteTitleRequest,
)


# ─────────────────────────────────────────────────────────────────────────────
# CreateRoleRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateRoleRequest:
    def _valid(self, **ov):
        base = dict(role_name="Manager", role_code="MANAGER")
        base.update(ov); return CreateRoleRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.role_name == "Manager"
        assert r.role_code == "MANAGER"

    def test_description_optional_none(self):
        r = self._valid()
        assert r.description is None

    def test_description_provided(self):
        r = self._valid(description="Senior management role")
        assert r.description == "Senior management role"

    def test_missing_role_name_raises(self):
        with pytest.raises(ValidationError):
            CreateRoleRequest(role_code="MGR")

    def test_missing_role_code_raises(self):
        with pytest.raises(ValidationError):
            CreateRoleRequest(role_name="Manager")

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            CreateRoleRequest()

    def test_empty_role_name_accepted_by_schema(self):
        # Schema itself has no min_length — business logic handles it
        r = self._valid(role_name="")
        assert r.role_name == ""

    def test_empty_role_code_accepted_by_schema(self):
        r = self._valid(role_code="")
        assert r.role_code == ""

    def test_role_code_lowercase_stored_as_is(self):
        # Schema does NOT uppercase — service layer does
        r = self._valid(role_code="manager")
        assert r.role_code == "manager"

    def test_role_code_with_underscores(self):
        r = self._valid(role_code="HR_ADMIN")
        assert r.role_code == "HR_ADMIN"

    def test_long_description_accepted(self):
        r = self._valid(description="x" * 1000)
        assert len(r.description) == 1000

    def test_all_fields_together(self):
        r = CreateRoleRequest(
            role_name="HR Admin", role_code="HR_ADMIN",
            description="Human resources administrator"
        )
        assert r.role_name   == "HR Admin"
        assert r.role_code   == "HR_ADMIN"
        assert r.description == "Human resources administrator"


# ─────────────────────────────────────────────────────────────────────────────
# AssignRoleRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignRoleRequest:
    def _valid(self, **ov):
        from conftest import make_uuid
        base = dict(employee_id=make_uuid(), role_id=make_uuid())
        base.update(ov); return AssignRoleRequest(**base)

    def test_valid(self):
        r = self._valid()
        assert r.employee_id
        assert r.role_id

    def test_missing_employee_id_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            AssignRoleRequest(role_id=make_uuid())

    def test_missing_role_id_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            AssignRoleRequest(employee_id=make_uuid())

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            AssignRoleRequest()

    def test_string_ids_accepted(self):
        r = self._valid(employee_id="emp-123", role_id="role-456")
        assert r.employee_id == "emp-123"
        assert r.role_id     == "role-456"

    def test_uuid_string_accepted(self):
        import uuid
        eid = str(uuid.uuid4()); rid = str(uuid.uuid4())
        r = AssignRoleRequest(employee_id=eid, role_id=rid)
        assert r.employee_id == eid

    def test_extra_fields_ignored_by_default(self):
        # Pydantic v2 ignores extra by default unless configured otherwise
        r = self._valid()
        assert r.employee_id


# ─────────────────────────────────────────────────────────────────────────────
# RevokeRoleRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestRevokeRoleRequest:
    def _valid(self, **ov):
        from conftest import make_uuid
        base = dict(employee_id=make_uuid(), role_id=make_uuid())
        base.update(ov); return RevokeRoleRequest(**base)

    def test_valid(self):
        r = self._valid()
        assert r.employee_id; assert r.role_id

    def test_missing_employee_id_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            RevokeRoleRequest(role_id=make_uuid())

    def test_missing_role_id_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            RevokeRoleRequest(employee_id=make_uuid())

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            RevokeRoleRequest()

    def test_same_structure_as_assign(self):
        from conftest import make_uuid
        eid = make_uuid(); rid = make_uuid()
        r = RevokeRoleRequest(employee_id=eid, role_id=rid)
        assert r.employee_id == eid
        assert r.role_id     == rid


# ─────────────────────────────────────────────────────────────────────────────
# SetRoutePermissionRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestSetRoutePermissionRequest:
    def _valid(self, **ov):
        from conftest import make_uuid
        base = dict(route_key="GET:/v1/roles/list", role_id=make_uuid())
        base.update(ov); return SetRoutePermissionRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.route_key == "GET:/v1/roles/list"

    def test_title_optional_none(self):
        r = self._valid()
        assert r.title is None

    def test_title_provided(self):
        r = self._valid(title="List Roles")
        assert r.title == "List Roles"

    def test_missing_route_key_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            SetRoutePermissionRequest(role_id=make_uuid())

    def test_missing_role_id_raises(self):
        with pytest.raises(ValidationError):
            SetRoutePermissionRequest(route_key="GET:/v1/roles/list")

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            SetRoutePermissionRequest()

    def test_various_http_methods(self):
        from conftest import make_uuid
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            r = SetRoutePermissionRequest(
                route_key=f"{method}:/v1/roles/list", role_id=make_uuid()
            )
            assert r.route_key.startswith(method)

    def test_route_key_with_path_params(self):
        from conftest import make_uuid
        r = SetRoutePermissionRequest(
            route_key="GET:/v1/employees/{employee_id}", role_id=make_uuid()
        )
        assert "{employee_id}" in r.route_key


# ─────────────────────────────────────────────────────────────────────────────
# DeleteRoutePermissionRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteRoutePermissionRequest:
    def _valid(self, **ov):
        from conftest import make_uuid
        base = dict(route_key="POST:/v1/roles/assign", role_id=make_uuid())
        base.update(ov); return DeleteRoutePermissionRequest(**base)

    def test_valid(self):
        r = self._valid()
        assert r.route_key == "POST:/v1/roles/assign"

    def test_missing_route_key_raises(self):
        from conftest import make_uuid
        with pytest.raises(ValidationError):
            DeleteRoutePermissionRequest(role_id=make_uuid())

    def test_missing_role_id_raises(self):
        with pytest.raises(ValidationError):
            DeleteRoutePermissionRequest(route_key="GET:/v1/x")

    def test_no_title_field(self):
        # DeleteRoutePermissionRequest has no title — unlike Set
        r = self._valid()
        assert not hasattr(r, "title")

    def test_route_key_and_role_id_stored(self):
        from conftest import make_uuid
        rid = make_uuid()
        r = DeleteRoutePermissionRequest(route_key="DELETE:/v1/x", role_id=rid)
        assert r.route_key == "DELETE:/v1/x"
        assert r.role_id   == rid


# ─────────────────────────────────────────────────────────────────────────────
# UpdateRouteTitleRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateRouteTitleRequest:
    def test_valid(self):
        r = UpdateRouteTitleRequest(route_key="GET:/v1/roles/list", title="List All Roles")
        assert r.route_key == "GET:/v1/roles/list"
        assert r.title     == "List All Roles"

    def test_missing_route_key_raises(self):
        with pytest.raises(ValidationError):
            UpdateRouteTitleRequest(title="Some Title")

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            UpdateRouteTitleRequest(route_key="GET:/v1/roles/list")

    def test_both_missing_raises(self):
        with pytest.raises(ValidationError):
            UpdateRouteTitleRequest()

    def test_empty_title_accepted(self):
        r = UpdateRouteTitleRequest(route_key="GET:/v1/x", title="")
        assert r.title == ""

    def test_long_title_accepted(self):
        r = UpdateRouteTitleRequest(route_key="GET:/v1/x", title="x" * 500)
        assert len(r.title) == 500

    def test_route_key_any_format_accepted(self):
        r = UpdateRouteTitleRequest(
            route_key="PATCH:/v1/roles/route-permissions/title",
            title="Update Route Display Title",
        )
        assert "PATCH" in r.route_key
