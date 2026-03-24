"""
src/employees/tests/test_regressions.py
─────────────────────────────────────────
Regression tests guarding known bugs and edge cases in the employee service.
"""
from __future__ import annotations
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import src.employees.service as svc
from src.employees.schemas import CreateEmployeeRequest, UpdateEmployeeRequest
from conftest import (
    _fake_employee, _fake_desig, _fake_dept, _fake_status,
    _fake_wallet, _fake_role, _fake_employee_role, make_uuid, utcnow, today,
)

_SVC = "src.employees.service"

def _noop_audit_ctx(**kwargs):
    @asynccontextmanager
    async def _cm(): yield
    return _cm()

def _make_new_emp(**ov):
    e = _fake_employee(**ov)
    e.status_master_employees_status_idTostatus_master = _fake_status(status_code="ACTIVE")
    return e


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: total_pages — no division-by-zero, ceil works correctly
# ─────────────────────────────────────────────────────────────────────────────
class TestPaginationEdgeCases:
    async def test_zero_total_gives_zero_pages(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=0)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(1, 20)
        assert r.pagination.total_pages == 0

    async def test_exact_page_boundary(self):
        """20 items / limit 20 = 1 page, not 0 pages."""
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=20)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(1, 20)
        assert r.pagination.total_pages == 1

    async def test_21_items_gives_2_pages(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=21)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(1, 20)
        assert r.pagination.total_pages == 2

    async def test_has_next_false_on_last_page(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=5)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(1, 20)
        assert r.pagination.has_next is False

    async def test_has_previous_false_on_first_page(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=50)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(1, 20)
        assert r.pagination.has_previous is False

    async def test_has_previous_true_on_second_page(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=50)
            mock_e.find_many = AsyncMock(return_value=[])
            r = await svc.list_employees(2, 20)
        assert r.pagination.has_previous is True


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: sort_by fallback — unknown fields default to created_at
# ─────────────────────────────────────────────────────────────────────────────
class TestSortByFallback:
    async def test_unknown_sort_field_falls_back_to_created_at(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=0)
            mock_e.find_many = AsyncMock(return_value=[])
            await svc.list_employees(1, 20, sort_by="malicious_field")
        kw = mock_e.find_many.call_args.kwargs
        assert "created_at" in kw["order"]

    async def test_invalid_sort_order_falls_back_to_desc(self):
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.count    = AsyncMock(return_value=0)
            mock_e.find_many = AsyncMock(return_value=[])
            await svc.list_employees(1, 20, sort_order="RANDOM")
        kw = mock_e.find_many.call_args.kwargs
        assert kw["order"].get("created_at") == "desc"

    async def test_valid_sort_fields_accepted(self):
        for field in ("created_at", "username", "date_of_joining"):
            with patch.object(svc.db, "employees") as mock_e:
                mock_e.count    = AsyncMock(return_value=0)
                mock_e.find_many = AsyncMock(return_value=[])
                await svc.list_employees(1, 20, sort_by=field)
            kw = mock_e.find_many.call_args.kwargs
            assert field in kw["order"]


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: update_employee — UUID fields must be cast to str before storage
# ─────────────────────────────────────────────────────────────────────────────
class TestUUIDStringCasting:
    async def test_department_id_stored_as_str(self):
        emp = _fake_employee(); did = uuid.uuid4()
        body = UpdateEmployeeRequest(department_id=did)
        with (
            patch.object(svc.db, "employees") as mock_e,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}._invalidate_employee_caches", new_callable=AsyncMock),
            patch(f"{_SVC}.get_employee_detail", new_callable=AsyncMock, return_value=MagicMock()),
        ):
            mock_e.find_unique = AsyncMock(return_value=emp)
            mock_e.update      = AsyncMock(return_value=emp)
            await svc.update_employee(str(emp.employee_id), body, make_uuid())
        update_data = mock_e.update.call_args.kwargs["data"]
        assert isinstance(update_data["department_id"], str)

    async def test_designation_id_stored_as_str(self):
        emp = _fake_employee(); did = uuid.uuid4()
        body = UpdateEmployeeRequest(designation_id=did)
        with (
            patch.object(svc.db, "employees") as mock_e,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}._invalidate_employee_caches", new_callable=AsyncMock),
            patch(f"{_SVC}.get_employee_detail", new_callable=AsyncMock, return_value=MagicMock()),
        ):
            mock_e.find_unique = AsyncMock(return_value=emp)
            mock_e.update      = AsyncMock(return_value=emp)
            await svc.update_employee(str(emp.employee_id), body, make_uuid())
        assert isinstance(mock_e.update.call_args.kwargs["data"]["designation_id"], str)

    async def test_manager_id_stored_as_str(self):
        emp = _fake_employee(); mid = uuid.uuid4()
        body = UpdateEmployeeRequest(manager_id=mid)
        with (
            patch.object(svc.db, "employees") as mock_e,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}._invalidate_employee_caches", new_callable=AsyncMock),
            patch(f"{_SVC}.get_employee_detail", new_callable=AsyncMock, return_value=MagicMock()),
        ):
            mock_e.find_unique = AsyncMock(return_value=emp)
            mock_e.update      = AsyncMock(return_value=emp)
            await svc.update_employee(str(emp.employee_id), body, make_uuid())
        assert isinstance(mock_e.update.call_args.kwargs["data"]["manager_id"], str)


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: password validator in CreateEmployeeRequest
# ─────────────────────────────────────────────────────────────────────────────
class TestPasswordValidation:
    def _base(self, **ov):
        base = dict(username="test.user", email="t@example.com", password="Secure1!",
                    designation_id=uuid.uuid4(), department_id=uuid.uuid4(),
                    manager_id=uuid.uuid4(), date_of_joining=date(2020, 1, 1),
                    status_id=uuid.uuid4())
        base.update(ov); return CreateEmployeeRequest(**base)

    def test_missing_uppercase_rejected(self):
        with pytest.raises(ValidationError): self._base(password="secure1!xyz")

    def test_missing_lowercase_rejected(self):
        with pytest.raises(ValidationError): self._base(password="SECURE1!XYZ")

    def test_missing_digit_rejected(self):
        with pytest.raises(ValidationError): self._base(password="SecureABC!")

    def test_missing_special_char_rejected(self):
        with pytest.raises(ValidationError): self._base(password="Secure1xyz")

    def test_all_criteria_met_accepted(self):
        r = self._base(password="Secure1!"); assert r.password == "Secure1!"

    def test_various_special_chars_accepted(self):
        for sp in ("!", "@", "#", "$", "%", "^", "&", "*"):
            r = self._base(password=f"Secure1{sp}"); assert r.password is not None


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: date validators in CreateEmployeeRequest
# ─────────────────────────────────────────────────────────────────────────────
class TestDateValidation:
    def _base(self, **ov):
        base = dict(username="user.x", email="x@example.com", password="Secure1!",
                    designation_id=uuid.uuid4(), department_id=uuid.uuid4(),
                    manager_id=uuid.uuid4(), date_of_joining=date(2020, 1, 1),
                    status_id=uuid.uuid4())
        base.update(ov); return CreateEmployeeRequest(**base)

    def test_future_doj_rejected(self):
        with pytest.raises(ValidationError): self._base(date_of_joining=date(2099, 1, 1))

    def test_today_doj_accepted(self):
        r = self._base(date_of_joining=today()); assert r.date_of_joining == today()

    def test_past_dob_accepted(self):
        r = self._base(date_of_birth=date(1990, 1, 1)); assert r.date_of_birth == date(1990, 1, 1)

    def test_future_dob_rejected(self):
        with pytest.raises(ValidationError): self._base(date_of_birth=date(2099, 1, 1))

    def test_today_dob_rejected(self):
        with pytest.raises(ValidationError): self._base(date_of_birth=today())


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: is_active derived from status relation — not a stored field
# ─────────────────────────────────────────────────────────────────────────────
class TestIsActiveDerivedFromStatus:
    async def test_active_status_code_gives_is_active_true(self):
        emp = _fake_employee(status=_fake_status(status_code="ACTIVE"))
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.find_unique = AsyncMock(return_value=emp)
            r = await svc.get_employee_detail(str(emp.employee_id))
        assert r.is_active is True

    async def test_inactive_status_code_gives_is_active_false(self):
        emp = _fake_employee(status=_fake_status(status_code="INACTIVE"))
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.find_unique = AsyncMock(return_value=emp)
            r = await svc.get_employee_detail(str(emp.employee_id))
        assert r.is_active is False

    async def test_missing_status_relation_gives_false(self):
        emp = _fake_employee()
        emp.status_master_employees_status_idTostatus_master = None
        with patch.object(svc.db, "employees") as mock_e:
            mock_e.find_unique = AsyncMock(return_value=emp)
            r = await svc.get_employee_detail(str(emp.employee_id))
        assert r.is_active is False


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: deactivate must use INACTIVE (not ACTIVE) status
# ─────────────────────────────────────────────────────────────────────────────
class TestDeactivateUsesInactiveStatus:
    async def test_inactive_status_id_used_in_update(self):
        inactive_id = make_uuid()
        inactive    = _fake_status(status_id=inactive_id, status_code="INACTIVE")
        emp         = _fake_employee()
        with (
            patch.object(svc.db, "status_master") as mock_sm,
            patch.object(svc.db, "employees")     as mock_e,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}._invalidate_employee_caches", new_callable=AsyncMock),
        ):
            mock_sm.find_first = AsyncMock(return_value=inactive)
            mock_e.find_unique  = AsyncMock(return_value=emp)
            mock_e.update       = AsyncMock(return_value=emp)
            await svc.patch_employee(str(emp.employee_id), make_uuid())
        update_data = mock_e.update.call_args.kwargs["data"]
        assert update_data["status_id"] == inactive_id

    async def test_active_status_not_used_for_deactivation(self):
        inactive = _fake_status(status_id="inactive-uuid", status_code="INACTIVE")
        active   = _fake_status(status_id="active-uuid",   status_code="ACTIVE")
        emp      = _fake_employee(status=active)
        with (
            patch.object(svc.db, "status_master") as mock_sm,
            patch.object(svc.db, "employees")     as mock_e,
            patch(f"{_SVC}.audit_ctx", side_effect=_noop_audit_ctx),
            patch(f"{_SVC}._invalidate_employee_caches", new_callable=AsyncMock),
        ):
            mock_sm.find_first = AsyncMock(return_value=inactive)
            mock_e.find_unique  = AsyncMock(return_value=emp)
            mock_e.update       = AsyncMock(return_value=emp)
            await svc.patch_employee(str(emp.employee_id), make_uuid())
        update_data = mock_e.update.call_args.kwargs["data"]
        assert update_data["status_id"] != "active-uuid"


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION: email is str (not EmailStr) in response schemas
# Ensures system accounts don't fail response serialisation
# ─────────────────────────────────────────────────────────────────────────────
class TestEmailIsStrInResponseSchemas:
    def test_employee_detail_accepts_non_email_string(self):
        from src.employees.schemas import EmployeeDetailResponse
        from datetime import datetime, date
        r = EmployeeDetailResponse(
            employee_id=uuid.uuid4(), username="sys",
            email="system@internal",   # not a valid email format
            date_of_joining=date(2020, 1, 1), is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        assert r.email == "system@internal"

    def test_employee_created_response_accepts_non_email_string(self):
        from src.employees.schemas import EmployeeCreatedResponse
        from datetime import datetime, date
        r = EmployeeCreatedResponse(
            employee_id=uuid.uuid4(), username="sys", email="sys@internal",
            designation_id=uuid.uuid4(), department_id=uuid.uuid4(),
            manager_id=uuid.uuid4(), date_of_joining=date(2020, 1, 1),
            status_id=uuid.uuid4(), is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        assert r.email == "sys@internal"

    def test_employee_list_item_accepts_non_email_string(self):
        from src.employees.schemas import EmployeeListItem
        from datetime import datetime, date
        r = EmployeeListItem(
            employee_id=uuid.uuid4(), username="sys", email="sys@internal",
            date_of_joining=date(2020, 1, 1), is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        assert r.email == "sys@internal"
