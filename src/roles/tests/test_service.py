"""
src/roles/tests/test_service.py
─────────────────────────────────
Unit tests for src/roles/service.py.
All Prisma DB and cache calls are patched.
Each test class covers one service function.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.roles.service as svc
from conftest import (
    _fake_role,
    _fake_employee_role,
    _fake_employee_stub,
    _fake_route_permission,
    _current_user,
    make_uuid,
    utcnow,
)

_SVC = "src.roles.service"


def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm(): yield
    return _cm()


# ══════════════════════════════════════════════════════════════════════════════
# list_roles
# ══════════════════════════════════════════════════════════════════════════════

class TestListRoles:
    async def test_returns_list_from_db(self):
        roles = [_fake_role(role_code="EMPLOYEE"), _fake_role(role_code="MANAGER")]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=roles)
            result = await svc.list_roles()
        assert len(result) == 2

    async def test_cache_hit_skips_db(self):
        cached = [{"role_id": make_uuid(), "role_code": "EMPLOYEE", "role_name": "Employee"}]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=cached),
            patch.object(svc.db, "roles") as mock_r,
        ):
            result = await svc.list_roles()
            mock_r.find_many.assert_not_awaited()
        assert result == cached

    async def test_cache_set_called_after_db(self):
        roles = [_fake_role()]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock) as mock_cs,
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=roles)
            await svc.list_roles()
        mock_cs.assert_awaited_once()

    async def test_empty_db_returns_empty_list(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            result = await svc.list_roles()
        assert result == []

    async def test_returns_serialised_dicts(self):
        role = _fake_role(role_code="HR_ADMIN")
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=[role])
            result = await svc.list_roles()
        assert isinstance(result[0], dict)

    async def test_cache_key_used(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None) as mock_cg,
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.list_roles()
        mock_cg.assert_awaited_once_with(svc._KEY_ROLES, l1_ttl=svc.L1_MEDIUM)

    async def test_ordered_by_role_name(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "roles") as mock_r,
        ):
            mock_r.find_many = AsyncMock(return_value=[])
            await svc.list_roles()
        kw = mock_r.find_many.call_args.kwargs
        assert kw["order"] == [{"role_name": "asc"}]


# ══════════════════════════════════════════════════════════════════════════════
# create_role
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateRole:
    def _body(self, **ov):
        from src.roles.schemas import CreateRoleRequest
        base = dict(role_name="HR Admin", role_code="hr_admin")
        base.update(ov); return CreateRoleRequest(**base)

    async def test_creates_role_when_no_duplicate(self):
        body    = self._body()
        created = _fake_role(role_code="HR_ADMIN")
        user    = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=created)
            result = await svc.create_role(body, user)
        assert result is created

    async def test_raises_409_on_duplicate_role_code(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "roles") as mock_r:
            mock_r.find_first = AsyncMock(return_value=_fake_role())
            with pytest.raises(HTTPException) as exc:
                await svc.create_role(body, user)
        assert exc.value.status_code == 409

    async def test_role_code_uppercased_before_check(self):
        body = self._body(role_code="hr_admin"); user = _current_user()
        with patch.object(svc.db, "roles") as mock_r:
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            with (
                patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
                patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
            ):
                await svc.create_role(body, user)
        # find_first called with uppercased code
        kw = mock_r.find_first.call_args.kwargs
        assert kw["where"]["role_code"] == "HR_ADMIN"

    async def test_role_code_stored_uppercase(self):
        body = self._body(role_code="manager"); user = _current_user()
        created = _fake_role()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=created)
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["role_code"] == "MANAGER"

    async def test_created_by_set_to_current_user(self):
        body = self._body(); uid = make_uuid(); user = _current_user(user_id=uid)
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["created_by"] == uid

    async def test_cache_invalidated_after_create(self):
        body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock) as mock_inv,
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        mock_inv.assert_awaited_once()

    async def test_duplicate_error_contains_role_code(self):
        body = self._body(role_code="SUPER_ADMIN"); user = _current_user()
        with patch.object(svc.db, "roles") as mock_r:
            mock_r.find_first = AsyncMock(return_value=_fake_role())
            with pytest.raises(HTTPException) as exc:
                await svc.create_role(body, user)
        assert "SUPER_ADMIN" in exc.value.detail

    async def test_description_stored(self):
        body = self._body(description="Admin role"); user = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["description"] == "Admin role"

    async def test_role_name_stored_as_provided(self):
        body = self._body(role_name="HR Admin"); user = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["role_name"] == "HR Admin"


# ══════════════════════════════════════════════════════════════════════════════
# list_employee_roles
# ══════════════════════════════════════════════════════════════════════════════

class TestListEmployeeRoles:
    async def test_returns_serialised_list(self):
        er = _fake_employee_role()
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        assert len(result) == 1

    async def test_cache_hit_skips_db(self):
        cached = [{"employee_role_id": make_uuid()}]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=cached),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            result = await svc.list_employee_roles()
            mock_er.find_many.assert_not_awaited()
        assert result == cached

    async def test_cache_set_called_after_db(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock) as mock_cs,
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[])
            await svc.list_employee_roles()
        mock_cs.assert_awaited_once()

    async def test_only_active_queried(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[])
            await svc.list_employee_roles()
        kw = mock_er.find_many.call_args.kwargs
        assert kw["where"]["is_active"] is True

    async def test_result_has_employee_and_role_keys(self):
        er  = _fake_employee_role()
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        item = result[0]
        assert "employee" in item
        assert "role"     in item

    async def test_employee_fields_in_result(self):
        emp = _fake_employee_stub(username="alice", email="alice@example.com")
        er  = _fake_employee_role(employee=emp)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        emp_dict = result[0]["employee"]
        assert emp_dict["username"] == "alice"
        assert emp_dict["email"]    == "alice@example.com"

    async def test_role_fields_in_result(self):
        role = _fake_role(role_code="MANAGER", role_name="Manager")
        er   = _fake_employee_role(role=role)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        role_dict = result[0]["role"]
        assert role_dict["code"] == "MANAGER"
        assert role_dict["name"] == "Manager"

    async def test_assigned_at_serialised_as_iso(self):
        er = _fake_employee_role()
        er.assigned_at = utcnow()
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        assert isinstance(result[0]["assigned_at"], str)

    async def test_none_assigned_at_serialised_as_none(self):
        er = _fake_employee_role()
        er.assigned_at = None
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[er])
            result = await svc.list_employee_roles()
        assert result[0]["assigned_at"] is None

    async def test_ordered_by_assigned_at_desc(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "employee_roles") as mock_er,
        ):
            mock_er.find_many = AsyncMock(return_value=[])
            await svc.list_employee_roles()
        kw = mock_er.find_many.call_args.kwargs
        assert kw["order"] == [{"assigned_at": "desc"}]


# ══════════════════════════════════════════════════════════════════════════════
# assign_role
# ══════════════════════════════════════════════════════════════════════════════

class TestAssignRole:
    def _body(self, employee_id=None, role_id=None):
        from src.roles.schemas import AssignRoleRequest
        return AssignRoleRequest(
            employee_id=employee_id or make_uuid(),
            role_id=role_id or make_uuid(),
        )

    async def test_creates_assignment_when_none_exists(self):
        body   = self._body(); user = _current_user()
        created = _fake_employee_role()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=created)
            result = await svc.assign_role(body, user)
        assert result is created

    async def test_raises_409_when_already_assigned(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_first = AsyncMock(return_value=_fake_employee_role())
            with pytest.raises(HTTPException) as exc:
                await svc.assign_role(body, user)
        assert exc.value.status_code == 409

    async def test_409_error_message(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_first = AsyncMock(return_value=_fake_employee_role())
            with pytest.raises(HTTPException) as exc:
                await svc.assign_role(body, user)
        assert "already has this role" in exc.value.detail.lower()

    async def test_checks_only_active_assignments(self):
        body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            await svc.assign_role(body, user)
        kw = mock_er.find_first.call_args.kwargs
        assert kw["where"]["is_active"] is True

    async def test_assigned_by_set_to_current_user(self):
        uid = make_uuid(); body = self._body(); user = _current_user(user_id=uid)
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            await svc.assign_role(body, user)
        create_data = mock_er.create.call_args.kwargs["data"]
        assert create_data["assigned_by"] == uid

    async def test_cache_invalidated_after_assign(self):
        body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock) as mock_inv,
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            await svc.assign_role(body, user)
        mock_inv.assert_awaited_once()

    async def test_employee_id_and_role_id_stored(self):
        eid = make_uuid(); rid = make_uuid()
        body = self._body(employee_id=eid, role_id=rid); user = _current_user()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            await svc.assign_role(body, user)
        create_data = mock_er.create.call_args.kwargs["data"]
        assert create_data["employee_id"] == eid
        assert create_data["role_id"]     == rid


# ══════════════════════════════════════════════════════════════════════════════
# revoke_role
# ══════════════════════════════════════════════════════════════════════════════

class TestRevokeRole:
    def _body(self, employee_id=None, role_id=None):
        from src.roles.schemas import RevokeRoleRequest
        return RevokeRoleRequest(
            employee_id=employee_id or make_uuid(),
            role_id=role_id or make_uuid(),
        )

    async def test_raises_404_when_no_active_assignment(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.revoke_role(body, user)
        assert exc.value.status_code == 404

    async def test_404_error_message(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.revoke_role(body, user)
        assert "active role assignment not found" in exc.value.detail.lower()

    async def test_sets_is_active_false(self):
        record = _fake_employee_role(); user = _current_user()
        body   = self._body(employee_id=record.employee_id, role_id=record.role_id)
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=record)
            mock_er.update     = AsyncMock(return_value=MagicMock())
            await svc.revoke_role(body, user)
        update_data = mock_er.update.call_args.kwargs["data"]
        assert update_data["is_active"] is False

    async def test_revoked_by_set_to_current_user(self):
        record = _fake_employee_role(); uid = make_uuid(); user = _current_user(user_id=uid)
        body   = self._body()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=record)
            mock_er.update     = AsyncMock(return_value=MagicMock())
            await svc.revoke_role(body, user)
        update_data = mock_er.update.call_args.kwargs["data"]
        assert update_data["revoked_by"] == uid

    async def test_revoked_at_set(self):
        record = _fake_employee_role(); user = _current_user()
        body   = self._body()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=record)
            mock_er.update     = AsyncMock(return_value=MagicMock())
            await svc.revoke_role(body, user)
        update_data = mock_er.update.call_args.kwargs["data"]
        assert "revoked_at" in update_data

    async def test_cache_invalidated_after_revoke(self):
        record = _fake_employee_role(); user = _current_user(); body = self._body()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock) as mock_inv,
        ):
            mock_er.find_first = AsyncMock(return_value=record)
            mock_er.update     = AsyncMock(return_value=MagicMock())
            await svc.revoke_role(body, user)
        mock_inv.assert_awaited_once()

    async def test_update_where_uses_record_id(self):
        record = _fake_employee_role(); user = _current_user(); body = self._body()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=record)
            mock_er.update     = AsyncMock(return_value=MagicMock())
            await svc.revoke_role(body, user)
        where_clause = mock_er.update.call_args.kwargs["where"]
        assert where_clause["employee_role_id"] == record.employee_role_id


# ══════════════════════════════════════════════════════════════════════════════
# list_route_permissions
# ══════════════════════════════════════════════════════════════════════════════

class TestListRoutePermissions:
    async def test_returns_grouped_list(self):
        role = _fake_role(role_code="SUPER_ADMIN")
        rp1  = _fake_route_permission(route_key="GET:/aabhar/v1/roles/list", role=role)
        rp2  = _fake_route_permission(route_key="GET:/aabhar/v1/roles/list", role=_fake_role(role_code="HR_ADMIN"))
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2])
            result = await svc.list_route_permissions()
        # Both rows have the same route_key → grouped into 1
        assert len(result) == 1
        assert len(result[0]["roles"]) == 2

    async def test_cache_hit_skips_db(self):
        cached = [{"route_key": "GET:/aabhar/v1/roles/list", "roles": []}]
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=cached),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            result = await svc.list_route_permissions()
            mock_rp.find_many.assert_not_awaited()
        assert result == cached

    async def test_cache_set_after_db(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock) as mock_cs,
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[])
            await svc.list_route_permissions()
        mock_cs.assert_awaited_once()

    async def test_only_active_queried(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[])
            await svc.list_route_permissions()
        kw = mock_rp.find_many.call_args.kwargs
        assert kw["where"]["is_active"] is True

    async def test_different_route_keys_not_merged(self):
        rp1 = _fake_route_permission(route_key="GET:/aabhar/v1/roles/list")
        rp2 = _fake_route_permission(route_key="POST:/aabhar/v1/roles/create")
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2])
            result = await svc.list_route_permissions()
        assert len(result) == 2

    async def test_title_taken_from_first_row_with_title(self):
        rp1 = _fake_route_permission(route_key="GET:/aabhar/v1/x", title=None)
        rp2 = _fake_route_permission(route_key="GET:/aabhar/v1/x", title="My Route")
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2])
            result = await svc.list_route_permissions()
        assert result[0]["title"] == "My Route"

    async def test_role_fields_in_grouped_result(self):
        role = _fake_role(role_code="MANAGER", role_name="Manager")
        rp   = _fake_route_permission(role=role)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp])
            result = await svc.list_route_permissions()
        role_entry = result[0]["roles"][0]
        assert role_entry["role_code"] == "MANAGER"
        assert role_entry["role_name"] == "Manager"

    async def test_empty_db_returns_empty_list(self):
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[])
            result = await svc.list_route_permissions()
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# add_route_permission
# ══════════════════════════════════════════════════════════════════════════════

class TestAddRoutePermission:
    def _body(self, route_key=None, role_id=None, title=None):
        from src.roles.schemas import SetRoutePermissionRequest
        return SetRoutePermissionRequest(
            route_key=route_key or "GET:/aabhar/v1/roles/list",
            role_id=role_id or make_uuid(),
            title=title,
        )

    async def test_creates_new_when_none_exists(self):
        body = self._body(); user = _current_user()
        created = _fake_route_permission()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            mock_rp.create     = AsyncMock(return_value=created)
            result = await svc.add_route_permission(body, user)
        assert result is created

    async def test_raises_409_when_active_perm_exists(self):
        body = self._body(); user = _current_user()
        existing = _fake_route_permission(is_active=True)
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_first = AsyncMock(return_value=existing)
            with pytest.raises(HTTPException) as exc:
                await svc.add_route_permission(body, user)
        assert exc.value.status_code == 409

    async def test_409_error_message(self):
        body = self._body(); user = _current_user()
        existing = _fake_route_permission(is_active=True)
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_first = AsyncMock(return_value=existing)
            with pytest.raises(HTTPException) as exc:
                await svc.add_route_permission(body, user)
        assert "already exists" in exc.value.detail.lower()

    async def test_reactivates_inactive_existing_permission(self):
        """If perm exists but is inactive, it should be updated (reactivated), not 409."""
        body     = self._body(); user = _current_user()
        inactive = _fake_route_permission(is_active=False)
        updated  = _fake_route_permission(is_active=True)
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=inactive)
            mock_rp.update     = AsyncMock(return_value=updated)
            result = await svc.add_route_permission(body, user)
        assert result is updated

    async def test_reactivation_sets_is_active_true(self):
        body     = self._body(); user = _current_user()
        inactive = _fake_route_permission(is_active=False)
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=inactive)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.add_route_permission(body, user)
        update_data = mock_rp.update.call_args.kwargs["data"]
        assert update_data["is_active"] is True

    async def test_create_stores_route_key(self):
        body = self._body(route_key="POST:/aabhar/v1/rewards/grant"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            mock_rp.create     = AsyncMock(return_value=_fake_route_permission())
            await svc.add_route_permission(body, user)
        create_data = mock_rp.create.call_args.kwargs["data"]
        assert create_data["route_key"] == "POST:/aabhar/v1/rewards/grant"

    async def test_create_stores_title(self):
        body = self._body(title="Grant Reward"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            mock_rp.create     = AsyncMock(return_value=_fake_route_permission())
            await svc.add_route_permission(body, user)
        create_data = mock_rp.create.call_args.kwargs["data"]
        assert create_data["title"] == "Grant Reward"

    async def test_cache_invalidated(self):
        body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock) as mock_inv,
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            mock_rp.create     = AsyncMock(return_value=_fake_route_permission())
            await svc.add_route_permission(body, user)
        mock_inv.assert_awaited_once()

    async def test_created_by_set(self):
        uid = make_uuid(); body = self._body(); user = _current_user(user_id=uid)
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            mock_rp.create     = AsyncMock(return_value=_fake_route_permission())
            await svc.add_route_permission(body, user)
        create_data = mock_rp.create.call_args.kwargs["data"]
        assert create_data["created_by"] == uid


# ══════════════════════════════════════════════════════════════════════════════
# remove_route_permission
# ══════════════════════════════════════════════════════════════════════════════

class TestRemoveRoutePermission:
    def _body(self, route_key=None, role_id=None):
        from src.roles.schemas import DeleteRoutePermissionRequest
        return DeleteRoutePermissionRequest(
            route_key=route_key or "GET:/aabhar/v1/roles/list",
            role_id=role_id or make_uuid(),
        )

    async def test_raises_404_when_no_active_permission(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.remove_route_permission(body, user)
        assert exc.value.status_code == 404

    async def test_404_error_message(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.remove_route_permission(body, user)
        assert "active permission not found" in exc.value.detail.lower()

    async def test_sets_is_active_false(self):
        record = _fake_route_permission(); user = _current_user()
        body   = self._body(route_key=record.route_key)
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=record)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.remove_route_permission(body, user)
        update_data = mock_rp.update.call_args.kwargs["data"]
        assert update_data["is_active"] is False

    async def test_updated_by_set(self):
        uid = make_uuid(); record = _fake_route_permission(); user = _current_user(user_id=uid)
        body = self._body()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=record)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.remove_route_permission(body, user)
        update_data = mock_rp.update.call_args.kwargs["data"]
        assert update_data["updated_by"] == uid

    async def test_update_where_uses_record_id(self):
        record = _fake_route_permission(); user = _current_user(); body = self._body()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=record)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.remove_route_permission(body, user)
        where_clause = mock_rp.update.call_args.kwargs["where"]
        assert where_clause["id"] == record.id

    async def test_cache_invalidated_after_remove(self):
        record = _fake_route_permission(); user = _current_user(); body = self._body()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock) as mock_inv,
        ):
            mock_rp.find_first = AsyncMock(return_value=record)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.remove_route_permission(body, user)
        mock_inv.assert_awaited_once()

    async def test_searches_only_active_permissions(self):
        body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException):
                await svc.remove_route_permission(body, user)
        kw = mock_rp.find_first.call_args.kwargs
        assert kw["where"]["is_active"] is True


# ══════════════════════════════════════════════════════════════════════════════
# update_route_title
# ══════════════════════════════════════════════════════════════════════════════

class TestUpdateRouteTitle:
    def _body(self, route_key=None, title=None):
        from src.roles.schemas import UpdateRouteTitleRequest
        return UpdateRouteTitleRequest(
            route_key=route_key or "GET:/aabhar/v1/roles/list",
            title=title or "Updated Title",
        )

    async def test_raises_404_when_no_rows_for_route_key(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_many   = AsyncMock(return_value=[])
            mock_rp.update_many = AsyncMock()
            with pytest.raises(HTTPException) as exc:
                await svc.update_route_title(body, user)
        assert exc.value.status_code == 404

    async def test_404_error_message(self):
        body = self._body(); user = _current_user()
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_many = AsyncMock(return_value=[])
            with pytest.raises(HTTPException) as exc:
                await svc.update_route_title(body, user)
        assert "no permissions" in exc.value.detail.lower()

    async def test_updates_all_rows_for_route_key(self):
        rows = [_fake_route_permission(), _fake_route_permission()]
        body = self._body(title="New Title"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        mock_rp.update_many.assert_awaited_once()

    async def test_title_stored_in_update_many(self):
        rows = [_fake_route_permission()]; body = self._body(title="Fresh Title"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        update_data = mock_rp.update_many.call_args.kwargs["data"]
        assert update_data["title"] == "Fresh Title"

    async def test_returns_route_key_and_title_and_updated_rows(self):
        rows = [_fake_route_permission(), _fake_route_permission()]
        body = self._body(route_key="GET:/aabhar/v1/x", title="My Title"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            result = await svc.update_route_title(body, user)
        assert result["route_key"]    == "GET:/aabhar/v1/x"
        assert result["title"]        == "My Title"
        assert result["updated_rows"] == 2

    async def test_audit_called_once(self):
        rows = [_fake_route_permission()]; body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock) as mock_audit,
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        mock_audit.assert_awaited_once()

    async def test_cache_invalidated_after_title_update(self):
        rows = [_fake_route_permission()]; body = self._body(); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock) as mock_inv,
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        mock_inv.assert_awaited_once()

    async def test_update_many_where_uses_route_key(self):
        rows = [_fake_route_permission()]; body = self._body(route_key="PATCH:/aabhar/v1/x"); user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        where_clause = mock_rp.update_many.call_args.kwargs["where"]
        assert where_clause["route_key"] == "PATCH:/aabhar/v1/x"


# ══════════════════════════════════════════════════════════════════════════════
# Cache invalidation helpers
# ══════════════════════════════════════════════════════════════════════════════

class TestCacheInvalidationHelpers:
    async def test_invalidate_roles_deletes_roles_key(self):
        with patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd:
            await svc.invalidate_roles()
        mock_cd.assert_awaited_once_with(svc._KEY_ROLES)

    async def test_invalidate_employee_roles_deletes_emp_roles_key(self):
        with patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd:
            await svc.invalidate_employee_roles()
        mock_cd.assert_awaited_once_with(svc._KEY_EMP_ROLES)

    async def test_invalidate_permissions_deletes_permissions_key(self):
        with patch(f"{_SVC}.cache_delete", new_callable=AsyncMock) as mock_cd:
            await svc.invalidate_permissions()
        mock_cd.assert_awaited_once_with(svc._KEY_PERMISSIONS)

    def test_key_constants_correct_values(self):
        assert svc._KEY_ROLES       == "roles:list"
        assert svc._KEY_EMP_ROLES   == "roles:employees"
        assert svc._KEY_PERMISSIONS == "roles:route_permissions"
