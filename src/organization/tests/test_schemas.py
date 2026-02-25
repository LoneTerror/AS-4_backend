"""
Tests for src/organization/schemas.py
Covers: all Pydantic schemas — validation, field constraints, validators
"""

import pytest
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import ValidationError

from src.organization.schemas import (
    DepartmentTypeResponse,
    ManagerBriefResponse,
    PaginationMeta,
    DepartmentListItem,
    DepartmentListResponse,
    DepartmentDetailResponse,
    CreateDepartmentRequest,
    UpdateDepartmentRequest,
    DepartmentCreatedResponse,
    DepartmentUpdatedResponse,
    DesignationListItem,
    DesignationListResponse,
    DesignationDetailResponse,
    CreateDesignationRequest,
    UpdateDesignationRequest,
)


NOW = datetime.now()
DEPT_ID = uuid4()
DESIG_ID = uuid4()
DEPT_TYPE_ID = uuid4()
MGR_ID = uuid4()


# ---------------------------------------------------------------------------
# DepartmentTypeResponse
# ---------------------------------------------------------------------------

class TestDepartmentTypeResponse:

    def test_valid(self):
        resp = DepartmentTypeResponse(
            department_type_id=DEPT_TYPE_ID,
            type_name="Engineering",
            type_code="ENG",
        )
        assert resp.type_code == "ENG"

    def test_from_orm(self):
        class FakeOrm:
            department_type_id = DEPT_TYPE_ID
            type_name = "HR"
            type_code = "HR"

        resp = DepartmentTypeResponse.model_validate(FakeOrm())
        assert resp.type_name == "HR"


# ---------------------------------------------------------------------------
# ManagerBriefResponse
# ---------------------------------------------------------------------------

class TestManagerBriefResponse:

    def test_email_optional(self):
        mgr = ManagerBriefResponse(employee_id=MGR_ID, username="mgr")
        assert mgr.email is None

    def test_full_manager(self):
        mgr = ManagerBriefResponse(
            employee_id=MGR_ID,
            username="mgr",
            email="mgr@x.com",
        )
        assert mgr.email == "mgr@x.com"


# ---------------------------------------------------------------------------
# PaginationMeta
# ---------------------------------------------------------------------------

class TestPaginationMeta:

    def test_valid_pagination(self):
        meta = PaginationMeta(
            current_page=2,
            per_page=20,
            total=100,
            total_pages=5,
            has_next=True,
            has_previous=True,
        )
        assert meta.total_pages == 5

    def test_first_page_has_no_previous(self):
        meta = PaginationMeta(
            current_page=1,
            per_page=20,
            total=40,
            total_pages=2,
            has_next=True,
            has_previous=False,
        )
        assert meta.has_previous is False


# ---------------------------------------------------------------------------
# DepartmentListItem
# ---------------------------------------------------------------------------

class TestDepartmentListItem:

    def test_minimal_valid(self):
        item = DepartmentListItem(
            department_id=DEPT_ID,
            department_name="Engineering",
            department_code="ENG",
            is_active=True,
            created_at=NOW,
        )
        assert item.department_code == "ENG"
        assert item.department_type is None
        assert item.manager is None


# ---------------------------------------------------------------------------
# DepartmentListResponse
# ---------------------------------------------------------------------------

class TestDepartmentListResponse:

    def test_empty_data(self):
        meta = PaginationMeta(
            current_page=1, per_page=20, total=0,
            total_pages=1, has_next=False, has_previous=False,
        )
        resp = DepartmentListResponse(data=[], pagination=meta)
        assert resp.data == []


# ---------------------------------------------------------------------------
# CreateDepartmentRequest
# ---------------------------------------------------------------------------

class TestCreateDepartmentRequest:

    def test_valid_request(self):
        req = CreateDepartmentRequest(
            department_name="Finance",
            department_code="fin",
            department_type_id=DEPT_TYPE_ID,
        )
        assert req.department_code == "FIN"  # auto-uppercased

    def test_code_uppercased_automatically(self):
        req = CreateDepartmentRequest(
            department_name="Sales",
            department_code="sales",
            department_type_id=DEPT_TYPE_ID,
        )
        assert req.department_code == "SALES"

    def test_code_too_long_raises(self):
        with pytest.raises(ValidationError):
            CreateDepartmentRequest(
                department_name="Sales",
                department_code="A" * 21,  # max 20
                department_type_id=DEPT_TYPE_ID,
            )

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            CreateDepartmentRequest(
                department_name="A" * 256,
                department_code="SALES",
                department_type_id=DEPT_TYPE_ID,
            )

    def test_manager_id_optional(self):
        req = CreateDepartmentRequest(
            department_name="IT",
            department_code="IT",
            department_type_id=DEPT_TYPE_ID,
        )
        assert req.manager_id is None


# ---------------------------------------------------------------------------
# UpdateDepartmentRequest
# ---------------------------------------------------------------------------

class TestUpdateDepartmentRequest:

    def test_all_fields_optional(self):
        req = UpdateDepartmentRequest()
        assert req.department_name is None
        assert req.is_active is None

    def test_partial_update(self):
        req = UpdateDepartmentRequest(department_name="New Name")
        assert req.department_name == "New Name"

    def test_code_uppercased_on_update(self):
        req = UpdateDepartmentRequest(department_code="marketing")
        assert req.department_code == "MARKETING"

    def test_none_code_stays_none(self):
        req = UpdateDepartmentRequest(department_code=None)
        assert req.department_code is None


# ---------------------------------------------------------------------------
# DesignationListItem / CreateDesignationRequest / UpdateDesignationRequest
# ---------------------------------------------------------------------------

class TestDesignationListItem:

    def test_valid_item(self):
        item = DesignationListItem(
            designation_id=DESIG_ID,
            designation_name="Software Engineer",
            designation_code="SWE",
            level=3,
            is_active=True,
            created_at=NOW,
        )
        assert item.level == 3


class TestCreateDesignationRequest:

    def test_valid_request(self):
        req = CreateDesignationRequest(
            designation_name="Junior Developer",
            designation_code="jr_dev",
            level=2,
        )
        assert req.designation_code == "JR_DEV"

    def test_level_must_be_at_least_1(self):
        with pytest.raises(ValidationError):
            CreateDesignationRequest(
                designation_name="Intern",
                designation_code="INT",
                level=0,  # invalid
            )

    def test_code_uppercased(self):
        req = CreateDesignationRequest(
            designation_name="Dev",
            designation_code="dev",
            level=1,
        )
        assert req.designation_code == "DEV"

    def test_description_optional(self):
        req = CreateDesignationRequest(
            designation_name="Dev",
            designation_code="DEV",
            level=1,
        )
        assert req.description is None


class TestUpdateDesignationRequest:

    def test_all_optional(self):
        req = UpdateDesignationRequest()
        assert req.designation_name is None
        assert req.level is None

    def test_level_below_1_raises(self):
        with pytest.raises(ValidationError):
            UpdateDesignationRequest(level=0)

    def test_code_uppercased_on_update(self):
        req = UpdateDesignationRequest(designation_code="lead")
        assert req.designation_code == "LEAD"


class TestDesignationDetailResponse:

    def test_valid(self):
        resp = DesignationDetailResponse(
            designation_id=DESIG_ID,
            designation_name="Lead",
            designation_code="LEAD",
            level=5,
            employee_count=10,
            is_active=True,
            created_at=NOW,
        )
        assert resp.employee_count == 10
        assert resp.description is None
