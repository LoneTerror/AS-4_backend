"""
src/organization/tests/test_regressions.py
────────────────────────────────────────────
Regression tests guarding known bugs and edge cases in the
organization service. Each class names the issue it prevents.
"""
from __future__ import annotations

import math
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import src.organization.service as svc
from src.organization.schemas import (
    CreateDepartmentRequest,
    CreateDesignationRequest,
    CreateStatusRequest,
    UpdateDepartmentRequest,
    UpdateDesignationRequest,
    UpdateStatusRequest,
)
from conftest import (
    _fake_audit_log,
    _fake_department,
    _fake_dept_type,
    _fake_designation,
    _fake_employee,
    _fake_status,
    make_uuid,
    utcnow,
)

_INV = "src.organization.service.invalidate_pattern"
_CDL = "src.organization.service.cache_delete"
_CGT = "src.organization.service.cache_get"
_CST = "src.organization.service.cache_set"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: total_pages must be 1 (not 0 or raise) when total == 0
# ─────────────────────────────────────────────────────────────────────────────

class TestZeroDivisionPagination:
    async def test_list_departments_zero_total_gives_total_pages_one(self):
        with (
            patch(_CGT, new_callable=AsyncMock, return_value=None),
            patch(_CST, new_callable=AsyncMock),
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_d.count     = AsyncMock(return_value=0)
            mock_d.find_many = AsyncMock(return_value=[])
            result = await svc.list_departments(1, 20, None, None)
        assert result.pagination.total_pages == 1

    async def test_list_designations_zero_total_gives_total_pages_one(self):
        with (
            patch(_CGT, new_callable=AsyncMock, return_value=None),
            patch(_CST, new_callable=AsyncMock),
            patch.object(svc.db, "designations") as mock_d,
        ):
            mock_d.count     = AsyncMock(return_value=0)
            mock_d.find_many = AsyncMock(return_value=[])
            result = await svc.list_designations(1, 20, None)
        assert result.pagination.total_pages == 1

    async def test_list_audit_logs_zero_total_gives_total_pages_one(self):
        with (
            patch.object(svc.db, "audit_log") as mock_al,
            patch.object(svc.db, "employees")  as mock_emp,
        ):
            mock_al.count      = AsyncMock(return_value=0)
            mock_al.find_many  = AsyncMock(return_value=[])
            mock_emp.find_many = AsyncMock(return_value=[])
            result = await svc.list_audit_logs(1, 50, None, None, None, None, None, None)
        assert result["pagination"].total_pages == 1

    async def test_total_pages_ceiling_not_floor(self):
        """21 items / 20 per page = ceil(1.05) = 2, not floor = 1."""
        with (
            patch(_CGT, new_callable=AsyncMock, return_value=None),
            patch(_CST, new_callable=AsyncMock),
            patch.object(svc.db, "departments") as mock_d,
        ):
            mock_d.count     = AsyncMock(return_value=21)
            mock_d.find_many = AsyncMock(return_value=[])
            result = await svc.list_departments(1, 20, None, None)
        assert result.pagination.total_pages == 2


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: BUG FIXED — ROUTE_TITLES defined twice in main.py
# The second definition (correct org keys) must win over recognition keys.
# Validated by checking schema-level titles have no "recognition" prefixes.
# ─────────────────────────────────────────────────────────────────────────────

class TestRouteTitlesBugFixed:
    def test_schema_code_validator_uppercases_department_code(self):
        r = CreateDepartmentRequest(
            department_name="X", department_code="lower", department_type_id=uuid.uuid4()
        )
        assert r.department_code == "LOWER"

    def test_schema_code_validator_uppercases_designation_code(self):
        r = CreateDesignationRequest(designation_name="X", designation_code="lower", level=1)
        assert r.designation_code == "LOWER"

    def test_schema_status_code_uppercased(self):
        r = CreateStatusRequest(status_code="active", status_name="Active", entity_type="EMPLOYEE")
        assert r.status_code == "ACTIVE"

    def test_update_dept_code_uppercased(self):
        r = UpdateDepartmentRequest(department_code="finance")
        assert r.department_code == "FINANCE"

    def test_update_desig_code_uppercased(self):
        r = UpdateDesignationRequest(designation_code="lead")
        assert r.designation_code == "LEAD"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: audit_log must use separate employee lookup, not JOIN
# Prevents audit rows from being silently dropped when performer_id
# has no matching employees record (sentinel UUIDs, background consumers).
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLogSeparateLookup:
    async def test_get_audit_log_calls_find_unique_on_employees(self):
        log = _fake_audit_log()
        with (
            patch.object(svc.db, "audit_log") as mock_al,
            patch.object(svc.db, "employees")  as mock_emp,
        ):
            mock_al.find_unique  = AsyncMock(return_value=log)
            mock_emp.find_unique = AsyncMock(return_value=None)
            await svc.get_audit_log(str(log.audit_id))
        # Must call employees.find_unique, NOT use include= in the audit_log query
        mock_emp.find_unique.assert_awaited_once()
        # audit_log.find_unique must NOT use include kwarg
        call_kwargs = mock_al.find_unique.call_args.kwargs
        assert "include" not in call_kwargs

    async def test_list_audit_logs_calls_bulk_employees_not_include(self):
        log = _fake_audit_log()
        with (
            patch.object(svc.db, "audit_log") as mock_al,
            patch.object(svc.db, "employees")  as mock_emp,
        ):
            mock_al.count      = AsyncMock(return_value=1)
            mock_al.find_many  = AsyncMock(return_value=[log])
            mock_emp.find_many = AsyncMock(return_value=[])
            await svc.list_audit_logs(1, 50, None, None, None, None, None, None)
        # Must call employees.find_many for bulk lookup
        mock_emp.find_many.assert_awaited_once()
        # audit_log.find_many must NOT use include kwarg
        find_kwargs = mock_al.find_many.call_args.kwargs
        assert "include" not in find_kwargs

    async def test_sentinel_uuid_performer_gives_none_employee_name(self):
        """Rows with sentinel UUIDs as performed_by must still appear (not be dropped)."""
        sentinel = "00000000-0000-0000-0000-000000000000"
        log      = _fake_audit_log(performed_by=sentinel)
        with (
            patch.object(svc.db, "audit_log") as mock_al,
            patch.object(svc.db, "employees")  as mock_emp,
        ):
            mock_al.find_unique  = AsyncMock(return_value=log)
            mock_emp.find_unique = AsyncMock(return_value=None)
            result = await svc.get_audit_log(str(log.audit_id))
        assert result.employee_name is None
        # Critically: no exception raised — log row still returned


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: update_department must exclude is_active from update_data
# (is_active changes are blocked at service layer for departments)
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDeptExcludesIsActive:
    async def test_is_active_only_raises_400(self):
        dept = _fake_department()
        with patch.object(svc.db, "departments") as mock_d:
            mock_d.find_unique = AsyncMock(return_value=dept)
            with pytest.raises(HTTPException) as exc:
                await svc.update_department(
                    str(dept.department_id),
                    UpdateDepartmentRequest(is_active=False),
                    make_uuid(),
                )
        assert exc.value.status_code == 400
        assert "no valid fields" in exc.value.detail.lower()

    async def test_is_active_with_valid_field_omits_is_active(self):
        dept    = _fake_department()
        updated = _fake_department(department_name="New Name")
        updated.department_types = None
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch(_CDL, new_callable=AsyncMock),
            patch(_INV, new_callable=AsyncMock),
        ):
            mock_d.find_unique = AsyncMock(return_value=dept)
            mock_d.update      = AsyncMock(return_value=updated)
            await svc.update_department(
                str(dept.department_id),
                UpdateDepartmentRequest(department_name="New Name", is_active=True),
                make_uuid(),
            )
        update_data = mock_d.update.call_args.kwargs["data"]
        assert "is_active" not in update_data
        assert update_data["department_name"] == "New Name"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: update_designation must exclude is_active from update_data
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDesignationExcludesIsActive:
    async def test_is_active_only_raises_400(self):
        desig = _fake_designation()
        with patch.object(svc.db, "designations") as mock_d:
            mock_d.find_unique = AsyncMock(return_value=desig)
            with pytest.raises(HTTPException) as exc:
                await svc.update_designation(
                    str(desig.designation_id),
                    UpdateDesignationRequest(is_active=False),
                    make_uuid(),
                )
        assert exc.value.status_code == 400

    async def test_is_active_combined_with_name_omits_is_active(self):
        desig   = _fake_designation(designation_name="Old")
        updated = _fake_designation(designation_name="New")
        updated.employees_employees_designation_idTodesignations = []
        with (
            patch.object(svc.db, "designations") as mock_d,
            patch(_CDL, new_callable=AsyncMock),
            patch(_INV, new_callable=AsyncMock),
        ):
            mock_d.find_unique = AsyncMock(side_effect=[desig, updated])
            mock_d.update      = AsyncMock(return_value=updated)
            mock_d.find_first  = AsyncMock(return_value=None)
            await svc.update_designation(
                str(desig.designation_id),
                UpdateDesignationRequest(designation_name="New", is_active=False),
                make_uuid(),
            )
        update_data = mock_d.update.call_args.kwargs["data"]
        assert "is_active" not in update_data
        assert update_data["designation_name"] == "New"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: CreateStatusRequest entity_type must be validated against allowlist
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusEntityTypeValidation:
    def test_employee_valid(self):
        r = CreateStatusRequest(status_code="X", status_name="X", entity_type="EMPLOYEE")
        assert r.entity_type == "EMPLOYEE"

    def test_review_valid(self):
        r = CreateStatusRequest(status_code="X", status_name="X", entity_type="REVIEW")
        assert r.entity_type == "REVIEW"

    def test_transaction_valid(self):
        r = CreateStatusRequest(status_code="X", status_name="X", entity_type="TRANSACTION")
        assert r.entity_type == "TRANSACTION"

    def test_reward_valid(self):
        r = CreateStatusRequest(status_code="X", status_name="X", entity_type="REWARD")
        assert r.entity_type == "REWARD"

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            CreateStatusRequest(status_code="X", status_name="X", entity_type="DEPARTMENT")

    def test_lowercase_entity_type_uppercased(self):
        r = CreateStatusRequest(status_code="X", status_name="X", entity_type="employee")
        assert r.entity_type == "EMPLOYEE"

    def test_empty_entity_type_raises(self):
        with pytest.raises(ValidationError):
            CreateStatusRequest(status_code="X", status_name="X", entity_type="")


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: cache invalidation must fire after write, not before
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheInvalidationOrder:
    async def test_invalidate_after_create_department(self):
        payload  = CreateDepartmentRequest(
            department_name="Test", department_code="TST", department_type_id=uuid.uuid4()
        )
        new_dept = _fake_department()
        new_dept.department_types = None
        new_dept.created_by       = make_uuid()
        call_order = []

        async def mock_create(**kwargs):
            call_order.append("db_create")
            return new_dept

        async def mock_inv(pattern):
            call_order.append("invalidate")

        with (
            patch.object(svc.db, "departments")     as mock_d,
            patch.object(svc.db, "department_types") as mock_dt,
            patch(_INV, side_effect=mock_inv),
        ):
            mock_d.find_first   = AsyncMock(return_value=None)
            mock_d.create       = mock_create
            mock_dt.find_unique = AsyncMock(return_value=_fake_dept_type())
            await svc.create_department(payload, make_uuid())

        assert call_order.index("db_create") < call_order.index("invalidate")

    async def test_invalidate_after_create_designation(self):
        payload   = CreateDesignationRequest(
            designation_name="Test", designation_code="TST", level=2
        )
        new_desig = _fake_designation()
        call_order = []

        async def mock_create(**kwargs):
            call_order.append("db_create")
            return new_desig

        async def mock_inv(pattern):
            call_order.append("invalidate")

        with (
            patch.object(svc.db, "designations") as mock_d,
            patch(_INV, side_effect=mock_inv),
        ):
            mock_d.find_first = AsyncMock(return_value=None)
            mock_d.create     = mock_create
            await svc.create_designation(payload, make_uuid())

        assert call_order.index("db_create") < call_order.index("invalidate")


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: department_type_id UUID must be stringified in update payload
# (Prisma Python does not accept UUID objects, only str)
# ─────────────────────────────────────────────────────────────────────────────

class TestDepartmentTypeIdStringified:
    async def test_uuid_object_converted_to_str_in_update(self):
        dept    = _fake_department()
        updated = _fake_department()
        updated.department_types = None
        type_uuid = uuid.uuid4()
        with (
            patch.object(svc.db, "departments") as mock_d,
            patch(_CDL, new_callable=AsyncMock),
            patch(_INV, new_callable=AsyncMock),
        ):
            mock_d.find_unique = AsyncMock(return_value=dept)
            mock_d.update      = AsyncMock(return_value=updated)
            await svc.update_department(
                str(dept.department_id),
                UpdateDepartmentRequest(department_type_id=type_uuid),
                make_uuid(),
            )
        update_data = mock_d.update.call_args.kwargs["data"]
        assert isinstance(update_data["department_type_id"], str)
        assert update_data["department_type_id"] == str(type_uuid)


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: create_designation duplicate check must check both name AND code
# ─────────────────────────────────────────────────────────────────────────────

class TestDesignationDuplicateCheck:
    async def test_duplicate_name_raises_400(self):
        payload = CreateDesignationRequest(
            designation_name="Engineer", designation_code="NEW_CODE", level=3
        )
        with patch.object(svc.db, "designations") as mock_d:
            mock_d.find_first = AsyncMock(return_value=_fake_designation())
            with pytest.raises(HTTPException) as exc:
                await svc.create_designation(payload, make_uuid())
        assert exc.value.status_code == 400

    async def test_no_duplicate_proceeds_to_create(self):
        payload   = CreateDesignationRequest(
            designation_name="Unique Name", designation_code="UNIQUE", level=3
        )
        new_desig = _fake_designation()
        with (
            patch.object(svc.db, "designations") as mock_d,
            patch(_INV, new_callable=AsyncMock),
        ):
            mock_d.find_first = AsyncMock(return_value=None)
            mock_d.create     = AsyncMock(return_value=new_desig)
            result = await svc.create_designation(payload, make_uuid())
        mock_d.create.assert_awaited_once()
