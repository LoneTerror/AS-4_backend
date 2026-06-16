"""
src/employees/tests/test_schemas.py
─────────────────────────────────────
Pydantic schema validation tests for src/employees/schemas.py.
No DB or IO — pure model-layer tests.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime
import pytest
from pydantic import ValidationError
from src.employees.schemas import (
    CreateEmployeeRequest, UpdateEmployeeRequest,
    DesignationResponse, DepartmentTypeResponse, DepartmentResponse,
    ManagerResponse, StatusResponse, WalletResponse, RoleResponse,
    EmployeeCreatedResponse, EmployeeDetailResponse,
    EmployeeListItem, EmployeeListResponse, PaginationMeta,
)

NOW      = datetime(2026, 1, 15, 10, 0, 0)
EMP_ID   = uuid.uuid4()
DESIG_ID = uuid.uuid4()
DEPT_ID  = uuid.uuid4()
MGR_ID   = uuid.uuid4()
STAT_ID  = uuid.uuid4()
ROLE_ID  = uuid.uuid4()
WALL_ID  = uuid.uuid4()
PAST_DOB = date(1990, 6, 15)
PAST_DOJ = date(2020, 3, 1)


# ─────────────────────────────────────────────────────────────────────────────
# CreateEmployeeRequest
# ─────────────────────────────────────────────────────────────────────────────
class TestCreateEmployeeRequest:
    def _valid(self, **ov):
        base = dict(
            username="john.doe",
            email="john@example.com",
            password="Secure1!",
            designation_id=DESIG_ID,
            department_id=DEPT_ID,
            manager_id=MGR_ID,
            date_of_joining=PAST_DOJ,
            status_id=STAT_ID,
        )
        base.update(ov); return CreateEmployeeRequest(**base)

    # username
    def test_valid_minimal(self):
        r = self._valid(); assert r.username == "john.doe"

    def test_username_min_length_ok(self):
        r = self._valid(username="abc"); assert r.username == "abc"

    def test_username_too_short_raises(self):
        with pytest.raises(ValidationError): self._valid(username="ab")

    def test_username_max_length_ok(self):
        r = self._valid(username="u" * 100); assert len(r.username) == 100

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError): self._valid(username="u" * 101)

    # email
    def test_valid_email(self):
        r = self._valid(email="user@domain.com"); assert "@" in r.email

    def test_invalid_email_raises(self):
        with pytest.raises(ValidationError): self._valid(email="not-email")

    # password validators
    def test_password_min_length_ok(self):
        r = self._valid(password="Abc1!xyz"); assert len(r.password) >= 8

    def test_password_too_short_raises(self):
        with pytest.raises(ValidationError): self._valid(password="Ab1!")

    def test_password_no_uppercase_raises(self):
        with pytest.raises(ValidationError): self._valid(password="abc123!x")

    def test_password_no_lowercase_raises(self):
        with pytest.raises(ValidationError): self._valid(password="ABC123!X")

    def test_password_no_digit_raises(self):
        with pytest.raises(ValidationError): self._valid(password="Abcdef!x")

    def test_password_no_special_raises(self):
        with pytest.raises(ValidationError): self._valid(password="Abcdef1x")

    def test_valid_password_all_criteria(self):
        r = self._valid(password="Secure1!"); assert r.password == "Secure1!"

    # UUIDs
    def test_designation_id_uuid(self):
        r = self._valid(); assert r.designation_id == DESIG_ID

    def test_invalid_uuid_raises(self):
        with pytest.raises(ValidationError): self._valid(designation_id="bad")

    # date_of_joining
    def test_past_doj_ok(self):
        r = self._valid(date_of_joining=date(2020, 1, 1)); assert r.date_of_joining == date(2020, 1, 1)

    def test_future_doj_raises(self):
        with pytest.raises(ValidationError): self._valid(date_of_joining=date(2099, 1, 1))

    # date_of_birth
    def test_no_dob_optional(self):
        r = self._valid(); assert r.date_of_birth is None

    def test_past_dob_ok(self):
        r = self._valid(date_of_birth=PAST_DOB); assert r.date_of_birth == PAST_DOB

    def test_future_dob_raises(self):
        with pytest.raises(ValidationError): self._valid(date_of_birth=date(2099, 1, 1))

    def test_today_dob_raises(self):
        with pytest.raises(ValidationError): self._valid(date_of_birth=date.today())

    def test_status_id_required(self):
        with pytest.raises(ValidationError):
            CreateEmployeeRequest(username="u" * 3, email="u@u.com", password="Secure1!",
                                  designation_id=DESIG_ID, department_id=DEPT_ID,
                                  manager_id=MGR_ID, date_of_joining=PAST_DOJ)

    def test_all_required_fields(self):
        r = self._valid()
        for field in ("username","email","password","designation_id",
                      "department_id","manager_id","date_of_joining","status_id"):
            assert getattr(r, field) is not None


# ─────────────────────────────────────────────────────────────────────────────
# UpdateEmployeeRequest
# ─────────────────────────────────────────────────────────────────────────────
class TestUpdateEmployeeRequest:
    def test_all_optional(self):
        r = UpdateEmployeeRequest(); assert r.username is None

    def test_username_only(self):
        r = UpdateEmployeeRequest(username="new.user"); assert r.username == "new.user"

    def test_username_too_short_raises(self):
        with pytest.raises(ValidationError): UpdateEmployeeRequest(username="ab")

    def test_username_max_length_ok(self):
        r = UpdateEmployeeRequest(username="u" * 100); assert len(r.username) == 100

    def test_username_too_long_raises(self):
        with pytest.raises(ValidationError): UpdateEmployeeRequest(username="u" * 101)

    def test_email_valid(self):
        r = UpdateEmployeeRequest(email="new@example.com"); assert "@" in r.email

    def test_email_invalid_raises(self):
        with pytest.raises(ValidationError): UpdateEmployeeRequest(email="bad")

    def test_designation_id_uuid(self):
        r = UpdateEmployeeRequest(designation_id=DESIG_ID); assert r.designation_id == DESIG_ID

    def test_invalid_designation_uuid_raises(self):
        with pytest.raises(ValidationError): UpdateEmployeeRequest(designation_id="bad")

    def test_all_fields_together(self):
        r = UpdateEmployeeRequest(
            username="updated.user", email="u@example.com",
            designation_id=DESIG_ID, department_id=DEPT_ID,
            manager_id=MGR_ID, status_id=STAT_ID,
            date_of_birth=PAST_DOB,
        )
        assert r.username == "updated.user"

    def test_date_of_birth_field(self):
        r = UpdateEmployeeRequest(date_of_birth=PAST_DOB); assert r.date_of_birth == PAST_DOB


# ─────────────────────────────────────────────────────────────────────────────
# Nested response models
# ─────────────────────────────────────────────────────────────────────────────
class TestDesignationResponse:
    def test_valid(self):
        r = DesignationResponse(designation_id=DESIG_ID, designation_name="Eng",
                                designation_code="ENG", level=3)
        assert r.level == 3

    def test_missing_level_raises(self):
        with pytest.raises(ValidationError):
            DesignationResponse(designation_id=DESIG_ID, designation_name="Eng",
                                designation_code="ENG")


class TestDepartmentTypeResponse:
    def test_valid(self):
        r = DepartmentTypeResponse(type_name="Engineering", type_code="ENG")
        assert r.type_code == "ENG"

    def test_missing_type_name_raises(self):
        with pytest.raises(ValidationError): DepartmentTypeResponse(type_code="ENG")


class TestDepartmentResponse:
    def test_valid_minimal(self):
        r = DepartmentResponse(department_id=DEPT_ID, department_name="Eng",
                               department_code="ENG")
        assert r.department_name == "Eng"

    def test_department_type_optional(self):
        r = DepartmentResponse(department_id=DEPT_ID, department_name="Eng",
                               department_code="ENG")
        assert r.department_type is None

    def test_with_dept_type(self):
        dt = DepartmentTypeResponse(type_name="Tech", type_code="TECH")
        r  = DepartmentResponse(department_id=DEPT_ID, department_name="Eng",
                                department_code="ENG", department_type=dt)
        assert r.department_type.type_code == "TECH"


class TestManagerResponse:
    def test_valid(self):
        r = ManagerResponse(employee_id=MGR_ID, username="mgr", email="mgr@example.com")
        assert r.username == "mgr"

    def test_email_is_str_not_emailstr(self):
        # Manager email is str — accepts system accounts
        r = ManagerResponse(employee_id=MGR_ID, username="sys", email="system@internal")
        assert r.email == "system@internal"

    def test_missing_username_raises(self):
        with pytest.raises(ValidationError):
            ManagerResponse(employee_id=MGR_ID, email="mgr@example.com")


class TestStatusResponse:
    def test_valid(self):
        r = StatusResponse(status_id=STAT_ID, status_code="ACTIVE", status_name="Active")
        assert r.status_code == "ACTIVE"


class TestWalletResponse:
    def test_valid(self):
        r = WalletResponse(wallet_id=WALL_ID, available_points=100,
                           redeemed_points=0, total_earned_points=100, version=1)
        assert r.available_points == 100

    def test_all_fields_required(self):
        with pytest.raises(ValidationError):
            WalletResponse(wallet_id=WALL_ID, available_points=100)


class TestRoleResponse:
    def test_valid(self):
        r = RoleResponse(role_id=ROLE_ID, role_name="Employee", role_code="EMPLOYEE")
        assert r.role_code == "EMPLOYEE"


# ─────────────────────────────────────────────────────────────────────────────
# EmployeeCreatedResponse
# ─────────────────────────────────────────────────────────────────────────────
class TestEmployeeCreatedResponse:
    def _make(self, **ov):
        base = dict(
            employee_id=EMP_ID, username="john.doe", email="john@example.com",
            designation_id=DESIG_ID, department_id=DEPT_ID, manager_id=MGR_ID,
            date_of_joining=PAST_DOJ, status_id=STAT_ID, is_active=True,
            created_at=NOW,
        )
        base.update(ov); return EmployeeCreatedResponse(**base)

    def test_valid_minimal(self):
        r = self._make(); assert r.username == "john.doe"

    def test_email_is_str(self):
        r = self._make(email="system@internal"); assert r.email == "system@internal"

    def test_wallet_optional(self):
        r = self._make(); assert r.wallet is None

    def test_with_wallet(self):
        w = WalletResponse(wallet_id=WALL_ID, available_points=0,
                           redeemed_points=0, total_earned_points=0, version=1)
        r = self._make(wallet=w); assert r.wallet.available_points == 0

    def test_dob_optional(self):
        r = self._make(); assert r.date_of_birth is None

    def test_created_by_optional(self):
        r = self._make(); assert r.created_by is None

    def test_missing_employee_id_raises(self):
        with pytest.raises(ValidationError):
            EmployeeCreatedResponse(username="x", email="x@x.com",
                                    designation_id=DESIG_ID, department_id=DEPT_ID,
                                    manager_id=MGR_ID, date_of_joining=PAST_DOJ,
                                    status_id=STAT_ID, is_active=True, created_at=NOW)


# ─────────────────────────────────────────────────────────────────────────────
# EmployeeDetailResponse
# ─────────────────────────────────────────────────────────────────────────────
class TestEmployeeDetailResponse:
    def _make(self, **ov):
        base = dict(
            employee_id=EMP_ID, username="john.doe", email="john@example.com",
            date_of_joining=PAST_DOJ, is_active=True, created_at=NOW,
        )
        base.update(ov); return EmployeeDetailResponse(**base)

    def test_valid_minimal(self):
        r = self._make(); assert r.employee_id == EMP_ID

    def test_all_nested_objects_optional(self):
        r = self._make()
        assert r.designation is None
        assert r.department  is None
        assert r.manager     is None
        assert r.status      is None
        assert r.wallet      is None

    def test_roles_default_empty_list(self):
        r = self._make(); assert r.roles == []

    def test_with_designation(self):
        d = DesignationResponse(designation_id=DESIG_ID, designation_name="Eng",
                                designation_code="ENG", level=3)
        r = self._make(designation=d); assert r.designation.level == 3

    def test_with_roles(self):
        role = RoleResponse(role_id=ROLE_ID, role_name="Manager", role_code="MANAGER")
        r    = self._make(roles=[role]); assert len(r.roles) == 1

    def test_updated_at_optional(self):
        r = self._make(); assert r.updated_at is None

    def test_created_by_optional(self):
        r = self._make(); assert r.created_by is None


# ─────────────────────────────────────────────────────────────────────────────
# EmployeeListItem
# ─────────────────────────────────────────────────────────────────────────────
class TestEmployeeListItem:
    def _make(self, **ov):
        base = dict(
            employee_id=EMP_ID, username="john.doe", email="john@example.com",
            date_of_joining=PAST_DOJ, is_active=True, created_at=NOW,
        )
        base.update(ov); return EmployeeListItem(**base)

    def test_valid_minimal(self):
        r = self._make(); assert r.username == "john.doe"

    def test_all_optional_fields_none(self):
        r = self._make()
        for f in ("designation_id","designation_name","department_id",
                  "department_name","manager_id","manager_name","status_id","status_name"):
            assert getattr(r, f) is None

    def test_with_optional_fields(self):
        r = self._make(
            designation_id=DESIG_ID, designation_name="Engineer",
            department_id=DEPT_ID, department_name="Eng",
            manager_id=MGR_ID, manager_name="Jane",
            status_id=STAT_ID, status_name="Active",
        )
        assert r.designation_name == "Engineer"
        assert r.department_name  == "Eng"
        assert r.manager_name     == "Jane"


# ─────────────────────────────────────────────────────────────────────────────
# PaginationMeta
# ─────────────────────────────────────────────────────────────────────────────
class TestPaginationMeta:
    def test_valid(self):
        p = PaginationMeta(current_page=1, per_page=20, total=50,
                           total_pages=3, has_next=True, has_previous=False)
        assert p.total_pages == 3

    def test_zero_total(self):
        p = PaginationMeta(current_page=1, per_page=20, total=0,
                           total_pages=0, has_next=False, has_previous=False)
        assert p.total == 0

    def test_has_previous_true(self):
        p = PaginationMeta(current_page=2, per_page=20, total=50,
                           total_pages=3, has_next=True, has_previous=True)
        assert p.has_previous is True


# ─────────────────────────────────────────────────────────────────────────────
# EmployeeListResponse
# ─────────────────────────────────────────────────────────────────────────────
class TestEmployeeListResponse:
    def test_valid(self):
        pg = PaginationMeta(current_page=1, per_page=20, total=0,
                            total_pages=0, has_next=False, has_previous=False)
        r  = EmployeeListResponse(data=[], pagination=pg)
        assert r.data == []

    def test_with_items(self):
        item = EmployeeListItem(employee_id=EMP_ID, username="john", email="j@j.com",
                                date_of_joining=PAST_DOJ, is_active=True, created_at=NOW)
        pg   = PaginationMeta(current_page=1, per_page=20, total=1,
                              total_pages=1, has_next=False, has_previous=False)
        r    = EmployeeListResponse(data=[item], pagination=pg)
        assert len(r.data) == 1
