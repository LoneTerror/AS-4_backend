"""
src/roles/tests/test_regressions.py
─────────────────────────────────────
Regression tests guarding known bugs and edge cases in the roles service.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import src.roles.service as svc
from src.roles.schemas import (
    CreateRoleRequest, AssignRoleRequest, RevokeRoleRequest,
    SetRoutePermissionRequest, DeleteRoutePermissionRequest,
    UpdateRouteTitleRequest,
)
from conftest import (
    _fake_role, _fake_employee_role, _fake_route_permission,
    _current_user, make_uuid, utcnow,
)

_SVC = "src.roles.service"


def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm(): yield
    return _cm()


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: role_code must always be stored UPPERCASE
# ─────────────────────────────────────────────────────────────────────────────

class TestRoleCodeUppercase:
    async def test_lowercase_input_uppercased_in_duplicate_check(self):
        body = CreateRoleRequest(role_name="Manager", role_code="manager")
        user = _current_user()
        with patch.object(svc.db, "roles") as mock_r:
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            with (
                patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
                patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
            ):
                await svc.create_role(body, user)
        kw = mock_r.find_first.call_args.kwargs
        assert kw["where"]["role_code"] == "MANAGER"

    async def test_mixed_case_uppercased_before_storage(self):
        body = CreateRoleRequest(role_name="HR Admin", role_code="hR_AdMiN")
        user = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["role_code"] == "HR_ADMIN"

    async def test_already_uppercase_unchanged(self):
        body = CreateRoleRequest(role_name="Employee", role_code="EMPLOYEE")
        user = _current_user()
        with (
            patch.object(svc.db, "roles") as mock_r,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_roles", new_callable=AsyncMock),
        ):
            mock_r.find_first = AsyncMock(return_value=None)
            mock_r.create     = AsyncMock(return_value=_fake_role())
            await svc.create_role(body, user)
        create_data = mock_r.create.call_args.kwargs["data"]
        assert create_data["role_code"] == "EMPLOYEE"

    async def test_409_uses_uppercased_code_in_message(self):
        body = CreateRoleRequest(role_name="Super Admin", role_code="super_admin")
        user = _current_user()
        with patch.object(svc.db, "roles") as mock_r:
            mock_r.find_first = AsyncMock(return_value=_fake_role())
            with pytest.raises(HTTPException) as exc:
                await svc.create_role(body, user)
        assert "SUPER_ADMIN" in exc.value.detail


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: assign_role must only check ACTIVE assignments for duplicates
# (a revoked assignment should allow reassignment)
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignOnlyChecksActiveAssignments:
    async def test_revoked_assignment_allows_reassign(self):
        """If the existing assignment is_active=False it was revoked;
        a new assign should succeed (find_first with is_active=True returns None)."""
        eid = make_uuid(); rid = make_uuid()
        body = AssignRoleRequest(employee_id=eid, role_id=rid)
        user = _current_user()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            # Active-only check finds nothing → assign proceeds
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            result = await svc.assign_role(body, user)
        mock_er.create.assert_awaited_once()

    async def test_duplicate_check_filters_is_active_true(self):
        eid = make_uuid(); rid = make_uuid()
        body = AssignRoleRequest(employee_id=eid, role_id=rid)
        user = _current_user()
        with (
            patch.object(svc.db, "employee_roles") as mock_er,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_employee_roles", new_callable=AsyncMock),
        ):
            mock_er.find_first = AsyncMock(return_value=None)
            mock_er.create     = AsyncMock(return_value=_fake_employee_role())
            await svc.assign_role(body, user)
        where = mock_er.find_first.call_args.kwargs["where"]
        assert where["is_active"] is True


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: revoke_role must NOT deactivate inactive assignments
# (find_first uses is_active=True → revoke 404s for already-revoked records)
# ─────────────────────────────────────────────────────────────────────────────

class TestRevokeOnlyDeactivatesActiveAssignments:
    async def test_revoke_404s_when_assignment_already_inactive(self):
        body = RevokeRoleRequest(employee_id=make_uuid(), role_id=make_uuid())
        user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            # Simulates no ACTIVE assignment found (already revoked)
            mock_er.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc:
                await svc.revoke_role(body, user)
        assert exc.value.status_code == 404

    async def test_revoke_find_first_filters_is_active_true(self):
        body = RevokeRoleRequest(employee_id=make_uuid(), role_id=make_uuid())
        user = _current_user()
        with patch.object(svc.db, "employee_roles") as mock_er:
            mock_er.find_first = AsyncMock(return_value=None)
            with pytest.raises(HTTPException):
                await svc.revoke_role(body, user)
        where = mock_er.find_first.call_args.kwargs["where"]
        assert where["is_active"] is True


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: add_route_permission must REACTIVATE soft-deleted rows,
# not create duplicates when a row exists but is_active=False
# ─────────────────────────────────────────────────────────────────────────────

class TestAddPermissionReactivatesInactiveRows:
    async def test_inactive_row_is_updated_not_created(self):
        rid      = make_uuid()
        body     = SetRoutePermissionRequest(route_key="GET:/v1/x", role_id=rid)
        user     = _current_user()
        inactive = _fake_route_permission(is_active=False)
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=inactive)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.add_route_permission(body, user)
        mock_rp.create.assert_not_awaited()
        mock_rp.update.assert_awaited_once()

    async def test_active_row_raises_409_not_duplicate_create(self):
        body   = SetRoutePermissionRequest(route_key="GET:/aabhar/v1/x", role_id=make_uuid())
        user   = _current_user()
        active = _fake_route_permission(is_active=True)
        with patch.object(svc.db, "route_permissions") as mock_rp:
            mock_rp.find_first = AsyncMock(return_value=active)
            with pytest.raises(HTTPException) as exc:
                await svc.add_route_permission(body, user)
        assert exc.value.status_code == 409
        mock_rp.create.assert_not_awaited()

    async def test_reactivation_preserves_existing_title_when_none_provided(self):
        """If body.title is None, the existing row's title should be kept."""
        body     = SetRoutePermissionRequest(route_key="GET:/aabhar/v1/x", role_id=make_uuid(), title=None)
        user     = _current_user()
        inactive = _fake_route_permission(is_active=False, title="Original Title")
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=inactive)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.add_route_permission(body, user)
        update_data = mock_rp.update.call_args.kwargs["data"]
        # title should fall back to existing.title ("Original Title")
        assert update_data["title"] == "Original Title"

    async def test_reactivation_uses_new_title_when_provided(self):
        body     = SetRoutePermissionRequest(route_key="GET:/aabhar/v1/x", role_id=make_uuid(), title="New Title")
        user     = _current_user()
        inactive = _fake_route_permission(is_active=False, title="Old Title")
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=inactive)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.add_route_permission(body, user)
        update_data = mock_rp.update.call_args.kwargs["data"]
        assert update_data["title"] == "New Title"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: remove_route_permission is a SOFT DELETE (is_active=False)
# not a hard delete — row must not be deleted from DB
# ─────────────────────────────────────────────────────────────────────────────

class TestSoftDeleteRoutePermission:
    async def test_db_delete_never_called(self):
        record = _fake_route_permission(); user = _current_user()
        body   = DeleteRoutePermissionRequest(
            route_key=record.route_key, role_id=record.role_id
        )
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_first = AsyncMock(return_value=record)
            mock_rp.update     = AsyncMock(return_value=MagicMock())
            await svc.remove_route_permission(body, user)
        mock_rp.delete.assert_not_awaited()
        mock_rp.delete_many.assert_not_awaited()

    async def test_is_active_explicitly_false_in_update(self):
        record = _fake_route_permission(); user = _current_user()
        body   = DeleteRoutePermissionRequest(
            route_key=record.route_key, role_id=record.role_id
        )
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


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: route_permissions grouped by route_key — multiple roles per key
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutePermissionGrouping:
    async def test_three_roles_same_key_grouped_into_one_entry(self):
        rp1 = _fake_route_permission(route_key="GET:/aabhar/v1/x", role=_fake_role(role_code="SUPER_ADMIN"))
        rp2 = _fake_route_permission(route_key="GET:/aabhar/v1/x", role=_fake_role(role_code="HR_ADMIN"))
        rp3 = _fake_route_permission(route_key="GET:/aabhar/v1/x", role=_fake_role(role_code="MANAGER"))
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2, rp3])
            result = await svc.list_route_permissions()
        assert len(result) == 1
        assert len(result[0]["roles"]) == 3

    async def test_two_different_keys_produce_two_entries(self):
        rp1 = _fake_route_permission(route_key="GET:/aabhar/v1/x")
        rp2 = _fake_route_permission(route_key="POST:/aabhar/v1/y")
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2])
            result = await svc.list_route_permissions()
        keys = {r["route_key"] for r in result}
        assert keys == {"GET:/aabhar/v1/x", "POST:/aabhar/v1/y"}

    async def test_title_not_overwritten_by_later_none_title(self):
        """First row sets title; second row has None → title should be kept."""
        rp1 = _fake_route_permission(route_key="GET:/aabhar/v1/x", title="My Title")
        rp2 = _fake_route_permission(route_key="GET:/aabhar/v1/x", title=None)
        with (
            patch(f"{_SVC}.cache_get", new_callable=AsyncMock, return_value=None),
            patch(f"{_SVC}.cache_set", new_callable=AsyncMock),
            patch.object(svc.db, "route_permissions") as mock_rp,
        ):
            mock_rp.find_many = AsyncMock(return_value=[rp1, rp2])
            result = await svc.list_route_permissions()
        assert result[0]["title"] == "My Title"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: update_route_title uses update_many — all rows updated atomically
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateRouteTitleUsesUpdateMany:
    async def test_update_many_called_once_regardless_of_row_count(self):
        rows = [_fake_route_permission() for _ in range(5)]
        body = UpdateRouteTitleRequest(route_key="GET:/aabhar/v1/x", title="Bulk")
        user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            await svc.update_route_title(body, user)
        # update_many called exactly once — not 5 individual updates
        mock_rp.update_many.assert_awaited_once()
        mock_rp.update.assert_not_awaited()

    async def test_updated_rows_count_matches_found_rows(self):
        rows = [_fake_route_permission() for _ in range(3)]
        body = UpdateRouteTitleRequest(route_key="GET:/aabhar/v1/x", title="New")
        user = _current_user()
        with (
            patch.object(svc.db, "route_permissions") as mock_rp,
            patch(f"{_SVC}.audit", new_callable=AsyncMock),
            patch(f"{_SVC}.invalidate_permissions", new_callable=AsyncMock),
        ):
            mock_rp.find_many   = AsyncMock(return_value=rows)
            mock_rp.update_many = AsyncMock(return_value=MagicMock())
            result = await svc.update_route_title(body, user)
        assert result["updated_rows"] == 3
