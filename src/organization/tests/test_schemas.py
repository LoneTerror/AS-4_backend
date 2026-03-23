"""
src/organization/tests/test_schemas.py
────────────────────────────────────────
Pydantic schema validation tests against the real src/organization/schemas.py.
No DB or IO involved — pure model-layer tests.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.organization.schemas import (
    AuditLogListResponse,
    AuditLogResponse,
    CreateDepartmentRequest,
    CreateDesignationRequest,
    CreateStatusRequest,
    DepartmentCreatedResponse,
    DepartmentDetailResponse,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentTypeResponse,
    DepartmentUpdatedResponse,
    DesignationDetailResponse,
    DesignationListItem,
    DesignationListResponse,
    ManagerBriefResponse,
    PaginationMeta,
    StatusDetailResponse,
    StatusResponse,
    UpdateDepartmentRequest,
    UpdateDesignationRequest,
    UpdateStatusRequest,
)

NOW       = datetime.now(timezone.utc)
DEPT_ID   = uuid.uuid4()
DTYPE_ID  = uuid.uuid4()
DESIG_ID  = uuid.uuid4()
STAT_ID   = uuid.uuid4()
EMP_ID    = uuid.uuid4()
AUDIT_ID  = uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# DepartmentTypeResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestDepartmentTypeResponse:
    def test_valid(self):
        r = DepartmentTypeResponse(
            department_type_id=DTYPE_ID, type_name="Engineering", type_code="ENG"
        )
        assert r.type_code == "ENG"

    def test_missing_type_name_raises(self):
        with pytest.raises(ValidationError):
            DepartmentTypeResponse(department_type_id=DTYPE_ID, type_code="ENG")

    def test_missing_type_code_raises(self):
        with pytest.raises(ValidationError):
            DepartmentTypeResponse(department_type_id=DTYPE_ID, type_name="Engineering")

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValidationError):
            DepartmentTypeResponse(department_type_id="not-a-uuid", type_name="X", type_code="X")

    def test_all_fields_stored(self):
        r = DepartmentTypeResponse(
            department_type_id=DTYPE_ID, type_name="HR", type_code="HR"
        )
        assert r.department_type_id == DTYPE_ID
        assert r.type_name == "HR"


# ─────────────────────────────────────────────────────────────────────────────
# ManagerBriefResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestManagerBriefResponse:
    def test_valid_minimal(self):
        r = ManagerBriefResponse(employee_id=EMP_ID, username="john.doe")
        assert r.employee_id == EMP_ID
        assert r.email is None

    def test_with_email(self):
        r = ManagerBriefResponse(employee_id=EMP_ID, username="john", email="j@x.com")
        assert r.email == "j@x.com"

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValidationError):
            ManagerBriefResponse(employee_id="not-uuid", username="x")

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError):
            ManagerBriefResponse(employee_id=EMP_ID)


# ─────────────────────────────────────────────────────────────────────────────
# PaginationMeta
# ─────────────────────────────────────────────────────────────────────────────

class TestPaginationMeta:
    def _make(self, **overrides):
        base = dict(
            current_page=1, per_page=20, total=50,
            total_pages=3, has_next=True, has_previous=False,
        )
        base.update(overrides)
        return PaginationMeta(**base)

    def test_valid(self):
        p = self._make()
        assert p.total_pages == 3
        assert p.has_next is True
        assert p.has_previous is False

    def test_last_page(self):
        p = self._make(current_page=3, has_next=False, has_previous=True)
        assert p.has_next is False
        assert p.has_previous is True

    def test_zero_total(self):
        p = self._make(total=0, total_pages=0, has_next=False)
        assert p.total == 0
        assert p.total_pages == 0

    def test_missing_field_raises(self):
        with pytest.raises(ValidationError):
            PaginationMeta(current_page=1, per_page=20)


# ─────────────────────────────────────────────────────────────────────────────
# CreateDepartmentRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateDepartmentRequest:
    def _valid(self, **overrides):
        base = dict(
            department_name="Engineering",
            department_code="eng",
            department_type_id=DTYPE_ID,
        )
        base.update(overrides)
        return CreateDepartmentRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.department_name == "Engineering"

    def test_code_uppercased(self):
        r = self._valid(department_code="eng")
        assert r.department_code == "ENG"

    def test_code_already_uppercase(self):
        r = self._valid(department_code="HR")
        assert r.department_code == "HR"

    def test_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(department_code="X" * 21)

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(department_name="x" * 256)

    def test_name_max_length_ok(self):
        r = self._valid(department_name="x" * 255)
        assert len(r.department_name) == 255

    def test_invalid_type_uuid_raises(self):
        with pytest.raises(ValidationError):
            self._valid(department_type_id="not-a-uuid")

    def test_manager_id_optional_none(self):
        r = self._valid()
        assert r.manager_id is None

    def test_manager_id_provided(self):
        r = self._valid(manager_id=EMP_ID)
        assert r.manager_id == EMP_ID

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            CreateDepartmentRequest(department_code="ENG", department_type_id=DTYPE_ID)

    def test_missing_code_raises(self):
        with pytest.raises(ValidationError):
            CreateDepartmentRequest(department_name="Eng", department_type_id=DTYPE_ID)

    def test_missing_type_id_raises(self):
        with pytest.raises(ValidationError):
            CreateDepartmentRequest(department_name="Eng", department_code="ENG")


# ─────────────────────────────────────────────────────────────────────────────
# UpdateDepartmentRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDepartmentRequest:
    def test_all_none_is_valid_schema(self):
        # Schema allows all-None; service layer raises 400 for no valid fields
        r = UpdateDepartmentRequest()
        assert r.department_name is None

    def test_code_uppercased(self):
        r = UpdateDepartmentRequest(department_code="finance")
        assert r.department_code == "FINANCE"

    def test_none_code_stays_none(self):
        r = UpdateDepartmentRequest(department_code=None)
        assert r.department_code is None

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            UpdateDepartmentRequest(department_name="x" * 256)

    def test_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            UpdateDepartmentRequest(department_code="X" * 21)

    def test_is_active_set(self):
        r = UpdateDepartmentRequest(is_active=False)
        assert r.is_active is False

    def test_manager_id_set(self):
        r = UpdateDepartmentRequest(manager_id=EMP_ID)
        assert r.manager_id == EMP_ID

    def test_partial_update_name_only(self):
        r = UpdateDepartmentRequest(department_name="New Name")
        assert r.department_name == "New Name"
        assert r.department_code is None


# ─────────────────────────────────────────────────────────────────────────────
# CreateDesignationRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateDesignationRequest:
    def _valid(self, **overrides):
        base = dict(designation_name="Engineer", designation_code="swe", level=3)
        base.update(overrides)
        return CreateDesignationRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.designation_name == "Engineer"

    def test_code_uppercased(self):
        r = self._valid(designation_code="swe")
        assert r.designation_code == "SWE"

    def test_level_must_be_positive(self):
        with pytest.raises(ValidationError):
            self._valid(level=0)

    def test_level_negative_raises(self):
        with pytest.raises(ValidationError):
            self._valid(level=-1)

    def test_level_one_ok(self):
        r = self._valid(level=1)
        assert r.level == 1

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(designation_name="x" * 101)

    def test_name_max_length_ok(self):
        r = self._valid(designation_name="x" * 100)
        assert len(r.designation_name) == 100

    def test_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(designation_code="X" * 51)

    def test_description_optional_none(self):
        r = self._valid()
        assert r.description is None

    def test_description_provided(self):
        r = self._valid(description="Senior dev role")
        assert r.description == "Senior dev role"

    def test_missing_level_raises(self):
        with pytest.raises(ValidationError):
            CreateDesignationRequest(designation_name="x", designation_code="X")


# ─────────────────────────────────────────────────────────────────────────────
# UpdateDesignationRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDesignationRequest:
    def test_all_none_allowed_by_schema(self):
        r = UpdateDesignationRequest()
        assert r.designation_name is None

    def test_code_uppercased(self):
        r = UpdateDesignationRequest(designation_code="manager")
        assert r.designation_code == "MANAGER"

    def test_none_code_stays_none(self):
        r = UpdateDesignationRequest(designation_code=None)
        assert r.designation_code is None

    def test_level_must_be_positive(self):
        with pytest.raises(ValidationError):
            UpdateDesignationRequest(level=0)

    def test_is_active_set(self):
        r = UpdateDesignationRequest(is_active=False)
        assert r.is_active is False

    def test_description_set(self):
        r = UpdateDesignationRequest(description="Updated desc")
        assert r.description == "Updated desc"

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            UpdateDesignationRequest(designation_name="x" * 101)


# ─────────────────────────────────────────────────────────────────────────────
# CreateStatusRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateStatusRequest:
    def _valid(self, **overrides):
        base = dict(
            status_code="active",
            status_name="Active",
            entity_type="EMPLOYEE",
        )
        base.update(overrides)
        return CreateStatusRequest(**base)

    def test_valid_minimal(self):
        r = self._valid()
        assert r.status_code == "ACTIVE"

    def test_status_code_uppercased(self):
        r = self._valid(status_code="pending")
        assert r.status_code == "PENDING"

    def test_entity_type_uppercased(self):
        r = self._valid(entity_type="employee")
        assert r.entity_type == "EMPLOYEE"

    def test_entity_type_review_valid(self):
        r = self._valid(entity_type="REVIEW")
        assert r.entity_type == "REVIEW"

    def test_entity_type_transaction_valid(self):
        r = self._valid(entity_type="TRANSACTION")
        assert r.entity_type == "TRANSACTION"

    def test_entity_type_reward_valid(self):
        r = self._valid(entity_type="REWARD")
        assert r.entity_type == "REWARD"

    def test_invalid_entity_type_raises(self):
        with pytest.raises(ValidationError):
            self._valid(entity_type="UNKNOWN_TYPE")

    def test_status_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(status_code="X" * 51)

    def test_status_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            self._valid(status_name="x" * 101)

    def test_description_optional(self):
        r = self._valid()
        assert r.description is None

    def test_description_provided(self):
        r = self._valid(description="Employee is active")
        assert r.description == "Employee is active"

    def test_missing_status_code_raises(self):
        with pytest.raises(ValidationError):
            CreateStatusRequest(status_name="Active", entity_type="EMPLOYEE")

    def test_missing_entity_type_raises(self):
        with pytest.raises(ValidationError):
            CreateStatusRequest(status_code="ACTIVE", status_name="Active")


# ─────────────────────────────────────────────────────────────────────────────
# UpdateStatusRequest
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateStatusRequest:
    def test_all_none_allowed(self):
        r = UpdateStatusRequest()
        assert r.status_name is None
        assert r.description is None

    def test_name_only(self):
        r = UpdateStatusRequest(status_name="Inactive")
        assert r.status_name == "Inactive"

    def test_description_only(self):
        r = UpdateStatusRequest(description="Newly inactive")
        assert r.description == "Newly inactive"

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            UpdateStatusRequest(status_name="x" * 101)

    def test_both_fields(self):
        r = UpdateStatusRequest(status_name="Paused", description="On hold")
        assert r.status_name == "Paused"
        assert r.description == "On hold"


# ─────────────────────────────────────────────────────────────────────────────
# DepartmentListItem / DepartmentListResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestDepartmentListItem:
    def _make(self, **overrides):
        base = dict(
            department_id=DEPT_ID,
            department_name="Engineering",
            department_code="ENG",
            is_active=True,
            created_at=NOW,
        )
        base.update(overrides)
        return DepartmentListItem(**base)

    def test_valid_minimal(self):
        r = self._make()
        assert r.department_code == "ENG"

    def test_optional_dept_type_none(self):
        r = self._make()
        assert r.department_type is None

    def test_with_dept_type(self):
        dt = DepartmentTypeResponse(
            department_type_id=DTYPE_ID, type_name="Tech", type_code="TECH"
        )
        r = self._make(department_type=dt)
        assert r.department_type.type_code == "TECH"

    def test_optional_manager_none(self):
        r = self._make()
        assert r.manager is None

    def test_inactive_department(self):
        r = self._make(is_active=False)
        assert r.is_active is False


class TestDepartmentListResponse:
    def _paginated(self, items=None):
        items = items or []
        return DepartmentListResponse(
            data=items,
            pagination=PaginationMeta(
                current_page=1, per_page=20, total=len(items),
                total_pages=1 if items else 0,
                has_next=False, has_previous=False,
            ),
        )

    def test_empty_data(self):
        r = self._paginated()
        assert r.data == []
        assert r.pagination.total == 0

    def test_with_items(self):
        item = DepartmentListItem(
            department_id=DEPT_ID, department_name="Eng",
            department_code="ENG", is_active=True, created_at=NOW,
        )
        r = self._paginated([item])
        assert len(r.data) == 1

    def test_missing_data_raises(self):
        with pytest.raises(ValidationError):
            DepartmentListResponse(pagination=PaginationMeta(
                current_page=1, per_page=20, total=0, total_pages=0,
                has_next=False, has_previous=False,
            ))

    def test_missing_pagination_raises(self):
        with pytest.raises(ValidationError):
            DepartmentListResponse(data=[])


# ─────────────────────────────────────────────────────────────────────────────
# DepartmentDetailResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestDepartmentDetailResponse:
    def _make(self, **overrides):
        base = dict(
            department_id=DEPT_ID, department_name="Eng",
            department_code="ENG", employee_count=5,
            is_active=True, created_at=NOW,
        )
        base.update(overrides)
        return DepartmentDetailResponse(**base)

    def test_valid(self):
        r = self._make()
        assert r.employee_count == 5

    def test_optional_updated_at(self):
        r = self._make()
        assert r.updated_at is None

    def test_with_updated_at(self):
        r = self._make(updated_at=NOW)
        assert r.updated_at is not None

    def test_optional_dept_type(self):
        r = self._make()
        assert r.department_type is None


# ─────────────────────────────────────────────────────────────────────────────
# DesignationListItem / DesignationListResponse / DesignationDetailResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestDesignationListItem:
    def _make(self, **overrides):
        base = dict(
            designation_id=DESIG_ID, designation_name="Engineer",
            designation_code="SWE", level=3, is_active=True, created_at=NOW,
        )
        base.update(overrides)
        return DesignationListItem(**base)

    def test_valid(self):
        r = self._make()
        assert r.level == 3

    def test_inactive(self):
        r = self._make(is_active=False)
        assert r.is_active is False

    def test_missing_level_raises(self):
        with pytest.raises(ValidationError):
            DesignationListItem(
                designation_id=DESIG_ID, designation_name="x",
                designation_code="X", is_active=True, created_at=NOW,
            )


class TestDesignationDetailResponse:
    def _make(self, **overrides):
        base = dict(
            designation_id=DESIG_ID, designation_name="Senior Engineer",
            designation_code="SWE3", level=5, employee_count=10,
            is_active=True, created_at=NOW,
        )
        base.update(overrides)
        return DesignationDetailResponse(**base)

    def test_valid(self):
        r = self._make()
        assert r.employee_count == 10

    def test_optional_description(self):
        r = self._make()
        assert r.description is None

    def test_description_provided(self):
        r = self._make(description="Senior level SWE")
        assert r.description == "Senior level SWE"

    def test_optional_updated_at(self):
        r = self._make()
        assert r.updated_at is None


# ─────────────────────────────────────────────────────────────────────────────
# StatusResponse / StatusDetailResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestStatusResponse:
    def _make(self, **overrides):
        base = dict(
            status_id=STAT_ID, status_code="ACTIVE",
            status_name="Active", entity_type="EMPLOYEE", created_at=NOW,
        )
        base.update(overrides)
        return StatusResponse(**base)

    def test_valid(self):
        r = self._make()
        assert r.status_code == "ACTIVE"
        assert r.entity_type == "EMPLOYEE"

    def test_optional_description(self):
        r = self._make()
        assert r.description is None

    def test_with_description(self):
        r = self._make(description="Employee is active")
        assert r.description == "Employee is active"

    def test_missing_status_code_raises(self):
        with pytest.raises(ValidationError):
            StatusResponse(
                status_id=STAT_ID, status_name="Active",
                entity_type="EMPLOYEE", created_at=NOW,
            )


class TestStatusDetailResponse:
    def test_inherits_status_response(self):
        r = StatusDetailResponse(
            status_id=STAT_ID, status_code="PENDING",
            status_name="Pending", entity_type="REVIEW", created_at=NOW,
        )
        assert r.status_code == "PENDING"
        assert r.updated_at is None

    def test_with_updated_at(self):
        r = StatusDetailResponse(
            status_id=STAT_ID, status_code="X", status_name="X",
            entity_type="EMPLOYEE", created_at=NOW, updated_at=NOW,
        )
        assert r.updated_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# AuditLogResponse
# ─────────────────────────────────────────────────────────────────────────────

class TestAuditLogResponse:
    def _make(self, **overrides):
        base = dict(
            audit_id=AUDIT_ID, table_name="departments",
            record_id=DEPT_ID, operation_type="INSERT",
            performed_by=EMP_ID, performed_at=NOW,
        )
        base.update(overrides)
        return AuditLogResponse(**base)

    def test_valid_minimal(self):
        r = self._make()
        assert r.table_name == "departments"
        assert r.operation_type == "INSERT"

    def test_optional_old_values(self):
        r = self._make()
        assert r.old_values is None

    def test_with_old_values(self):
        r = self._make(old_values={"department_name": "Old Name"})
        assert r.old_values["department_name"] == "Old Name"

    def test_optional_new_values(self):
        r = self._make()
        assert r.new_values is None

    def test_optional_ip_address(self):
        r = self._make()
        assert r.ip_address is None

    def test_optional_employee_name(self):
        r = self._make()
        assert r.employee_name is None

    def test_with_employee_fields(self):
        r = self._make(employee_name="john.doe", employee_email="j@example.com")
        assert r.employee_name == "john.doe"
        assert r.employee_email == "j@example.com"

    def test_missing_audit_id_raises(self):
        with pytest.raises(ValidationError):
            AuditLogResponse(
                table_name="departments", record_id=DEPT_ID,
                operation_type="INSERT", performed_by=EMP_ID, performed_at=NOW,
            )

    def test_missing_performed_by_raises(self):
        with pytest.raises(ValidationError):
            AuditLogResponse(
                audit_id=AUDIT_ID, table_name="departments",
                record_id=DEPT_ID, operation_type="INSERT", performed_at=NOW,
            )
