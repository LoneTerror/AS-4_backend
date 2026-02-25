"""
Tests for src/organization/service.py
Covers: list_departments, get_department_detail, create_department,
        update_department, list_department_types,
        list_designations, get_designation_detail,
        create_designation, update_designation
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime
from fastapi import HTTPException

from src.organization import schemas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = datetime.now()


def _make_dept(
    department_id=None,
    department_name="Engineering",
    department_code="ENG",
    dept_type=None,
):
    dept = MagicMock()
    dept.department_id = department_id or str(uuid4())
    dept.department_name = department_name
    dept.department_code = department_code
    dept.created_at = NOW
    dept.updated_at = NOW
    dept.created_by = str(uuid4())
    dept.updated_by = str(uuid4())
    dept.department_types = dept_type
    dept.employees_employees_department_idTodepartments = []
    return dept


def _make_dept_type():
    t = MagicMock()
    t.department_type_id = str(uuid4())
    t.type_name = "Core"
    t.type_code = "CORE"
    return t


def _make_desig(
    designation_id=None,
    designation_name="Engineer",
    designation_code="ENG",
    level=3,
):
    d = MagicMock()
    d.designation_id = designation_id or str(uuid4())
    d.designation_name = designation_name
    d.designation_code = designation_code
    d.level = level
    d.created_at = NOW
    d.updated_at = NOW
    d.created_by = str(uuid4())
    d.updated_by = str(uuid4())
    d.employees_employees_designation_idTodesignations = []
    return d


def _make_pagination_meta():
    return schemas.PaginationMeta(
        current_page=1,
        per_page=20,
        total=1,
        total_pages=1,
        has_next=False,
        has_previous=False,
    )


# ---------------------------------------------------------------------------
# list_departments
# ---------------------------------------------------------------------------

class TestListDepartments:

    @pytest.mark.asyncio
    async def test_returns_paginated_list(self):
        dept = _make_dept(dept_type=_make_dept_type())

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.count = AsyncMock(return_value=1)
            mock_db.departments.find_many = AsyncMock(return_value=[dept])

            from src.organization.service import list_departments
            result = await list_departments(page=1, limit=20, is_active=None, search=None)

        assert len(result.data) == 1
        assert result.data[0].department_name == "Engineering"
        assert result.pagination.total == 1

    @pytest.mark.asyncio
    async def test_empty_results(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.count = AsyncMock(return_value=0)
            mock_db.departments.find_many = AsyncMock(return_value=[])

            from src.organization.service import list_departments
            result = await list_departments(page=1, limit=20, is_active=None, search=None)

        assert result.data == []
        assert result.pagination.total == 0
        assert result.pagination.total_pages == 1

    @pytest.mark.asyncio
    async def test_search_filter_applied(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.count = AsyncMock(return_value=0)
            mock_db.departments.find_many = AsyncMock(return_value=[])

            from src.organization.service import list_departments
            result = await list_departments(page=1, limit=20, is_active=None, search="eng")

        # Verify count was called (search filter applied internally)
        mock_db.departments.count.assert_called_once()

    @pytest.mark.asyncio
    async def test_pagination_skip_calculated(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.count = AsyncMock(return_value=100)
            mock_db.departments.find_many = AsyncMock(return_value=[])

            from src.organization.service import list_departments
            await list_departments(page=3, limit=10, is_active=None, search=None)

        call_kwargs = mock_db.departments.find_many.call_args[1]
        assert call_kwargs["skip"] == 20  # (3-1) * 10

    @pytest.mark.asyncio
    async def test_department_without_type(self):
        dept = _make_dept(dept_type=None)

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.count = AsyncMock(return_value=1)
            mock_db.departments.find_many = AsyncMock(return_value=[dept])

            from src.organization.service import list_departments
            result = await list_departments(page=1, limit=20, is_active=None, search=None)

        assert result.data[0].department_type is None


# ---------------------------------------------------------------------------
# get_department_detail
# ---------------------------------------------------------------------------

class TestGetDepartmentDetail:

    @pytest.mark.asyncio
    async def test_returns_department_with_employee_count(self):
        dept = _make_dept(dept_type=_make_dept_type())
        dept.employees_employees_department_idTodepartments = [MagicMock(), MagicMock()]

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=dept)

            from src.organization.service import get_department_detail
            result = await get_department_detail(dept.department_id)

        assert result.employee_count == 2

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=None)

            from src.organization.service import get_department_detail

            with pytest.raises(HTTPException) as exc:
                await get_department_detail("nonexistent-id")

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_department_type_serialized(self):
        dept = _make_dept(dept_type=_make_dept_type())

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=dept)

            from src.organization.service import get_department_detail
            result = await get_department_detail(dept.department_id)

        assert result.department_type is not None
        assert result.department_type.type_code == "CORE"


# ---------------------------------------------------------------------------
# create_department
# ---------------------------------------------------------------------------

class TestCreateDepartment:

    def _payload(self):
        return schemas.CreateDepartmentRequest(
            department_name="New Dept",
            department_code="NEW",
            department_type_id=uuid4(),
        )

    @pytest.mark.asyncio
    async def test_creates_department_successfully(self):
        new_dept = _make_dept(dept_type=_make_dept_type())

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_first = AsyncMock(return_value=None)
            mock_db.department_types.find_unique = AsyncMock(return_value=MagicMock())
            mock_db.departments.create = AsyncMock(return_value=new_dept)

            from src.organization.service import create_department
            result = await create_department(self._payload(), "admin-id")

        assert result.department_name == "Engineering"

    @pytest.mark.asyncio
    async def test_duplicate_name_or_code_raises_400(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_first = AsyncMock(return_value=MagicMock())  # exists

            from src.organization.service import create_department

            with pytest.raises(HTTPException) as exc:
                await create_department(self._payload(), "admin-id")

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_department_type_raises_400(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_first = AsyncMock(return_value=None)
            mock_db.department_types.find_unique = AsyncMock(return_value=None)

            from src.organization.service import create_department

            with pytest.raises(HTTPException) as exc:
                await create_department(self._payload(), "admin-id")

        assert exc.value.status_code == 400
        assert "type" in exc.value.detail.lower()


# ---------------------------------------------------------------------------
# update_department
# ---------------------------------------------------------------------------

class TestUpdateDepartment:

    @pytest.mark.asyncio
    async def test_update_existing_department(self):
        updated = _make_dept(dept_type=_make_dept_type())

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=updated)
            mock_db.departments.update = AsyncMock(return_value=updated)

            from src.organization.service import update_department
            result = await update_department(
                updated.department_id,
                schemas.UpdateDepartmentRequest(department_name="Updated"),
                "admin-id",
            )

        assert result.department_id is not None

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=None)

            from src.organization.service import update_department

            with pytest.raises(HTTPException) as exc:
                await update_department(
                    "bad-id",
                    schemas.UpdateDepartmentRequest(department_name="X"),
                    "admin-id",
                )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_valid_fields_raises_400(self):
        existing = _make_dept()

        with patch("src.organization.service.db") as mock_db:
            mock_db.departments.find_unique = AsyncMock(return_value=existing)

            from src.organization.service import update_department

            with pytest.raises(HTTPException) as exc:
                # is_active is excluded from update_data in the service
                await update_department(
                    existing.department_id,
                    schemas.UpdateDepartmentRequest(is_active=True),
                    "admin-id",
                )

        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# list_department_types
# ---------------------------------------------------------------------------

class TestListDepartmentTypes:

    @pytest.mark.asyncio
    async def test_returns_list_of_schema_objects(self):
        t1 = _make_dept_type()
        t2 = _make_dept_type()

        with patch("src.organization.service.db") as mock_db:
            mock_db.department_types.find_many = AsyncMock(return_value=[t1, t2])

            from src.organization.service import list_department_types
            result = await list_department_types()

        assert len(result) == 2
        assert all(isinstance(r, schemas.DepartmentTypeResponse) for r in result)

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.department_types.find_many = AsyncMock(return_value=[])

            from src.organization.service import list_department_types
            result = await list_department_types()

        assert result == []


# ---------------------------------------------------------------------------
# list_designations
# ---------------------------------------------------------------------------

class TestListDesignations:

    @pytest.mark.asyncio
    async def test_returns_paginated_designations(self):
        desig = _make_desig()

        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.count = AsyncMock(return_value=1)
            mock_db.designations.find_many = AsyncMock(return_value=[desig])

            from src.organization.service import list_designations
            result = await list_designations(page=1, limit=20, is_active=None)

        assert len(result.data) == 1
        assert result.pagination.total == 1

    @pytest.mark.asyncio
    async def test_is_active_filter_ignored(self):
        """Designations table has no is_active column — filter is ignored without error."""
        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.count = AsyncMock(return_value=0)
            mock_db.designations.find_many = AsyncMock(return_value=[])

            from src.organization.service import list_designations
            # Should not raise even when is_active=True is passed
            result = await list_designations(page=1, limit=20, is_active=True)

        assert result.data == []


# ---------------------------------------------------------------------------
# get_designation_detail
# ---------------------------------------------------------------------------

class TestGetDesignationDetail:

    @pytest.mark.asyncio
    async def test_returns_designation(self):
        desig = _make_desig()
        desig.employees_employees_designation_idTodesignations = [MagicMock()]

        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_unique = AsyncMock(return_value=desig)

            from src.organization.service import get_designation_detail
            result = await get_designation_detail(desig.designation_id)

        assert result.employee_count == 1

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_unique = AsyncMock(return_value=None)

            from src.organization.service import get_designation_detail

            with pytest.raises(HTTPException) as exc:
                await get_designation_detail("bad-id")

        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# create_designation
# ---------------------------------------------------------------------------

class TestCreateDesignation:

    def _payload(self):
        return schemas.CreateDesignationRequest(
            designation_name="Senior Engineer",
            designation_code="SEN_ENG",
            level=4,
        )

    @pytest.mark.asyncio
    async def test_creates_designation(self):
        new_desig = _make_desig(designation_name="Senior Engineer", designation_code="SEN_ENG", level=4)

        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_first = AsyncMock(return_value=None)
            mock_db.designations.create = AsyncMock(return_value=new_desig)

            from src.organization.service import create_designation
            result = await create_designation(self._payload(), "admin-id")

        assert result.designation_code == "SEN_ENG"

    @pytest.mark.asyncio
    async def test_duplicate_raises_400(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_first = AsyncMock(return_value=MagicMock())

            from src.organization.service import create_designation

            with pytest.raises(HTTPException) as exc:
                await create_designation(self._payload(), "admin-id")

        assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# update_designation
# ---------------------------------------------------------------------------

class TestUpdateDesignation:

    @pytest.mark.asyncio
    async def test_updates_designation(self):
        existing = _make_desig()
        updated = _make_desig(designation_name="Principal Engineer", level=6)
        updated.employees_employees_designation_idTodesignations = []

        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_unique = AsyncMock(
                side_effect=[existing, updated]
            )
            mock_db.designations.update = AsyncMock(return_value=updated)

            from src.organization.service import update_designation
            result = await update_designation(
                existing.designation_id,
                schemas.UpdateDesignationRequest(designation_name="Principal Engineer", level=6),
                "admin-id",
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_unique = AsyncMock(return_value=None)

            from src.organization.service import update_designation

            with pytest.raises(HTTPException) as exc:
                await update_designation(
                    "bad-id",
                    schemas.UpdateDesignationRequest(designation_name="X"),
                    "admin-id",
                )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_valid_fields_raises_400(self):
        existing = _make_desig()

        with patch("src.organization.service.db") as mock_db:
            mock_db.designations.find_unique = AsyncMock(return_value=existing)

            from src.organization.service import update_designation

            with pytest.raises(HTTPException) as exc:
                # is_active and description are excluded from update_data
                await update_designation(
                    existing.designation_id,
                    schemas.UpdateDesignationRequest(is_active=True),
                    "admin-id",
                )

        assert exc.value.status_code == 400
