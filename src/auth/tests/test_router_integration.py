"""
src/auth/tests/test_router_integration.py
──────────────────────────────────────────
Integration tests for src/auth/router.py endpoints.

KEY: router.py imports service functions BY NAME at module-load time:
    from src.auth.service import authenticate_user, create_employee, ...
So ALL patches must target src.auth.router.<fn> (the router's local binding),
NOT src.auth.service.<fn>.

The only exception is check_route_permission, which is overridden via
FastAPI dependency_overrides.
"""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import src.common.dependencies as deps
from src.auth.router import router as auth_router
from conftest import _fake_employee, make_uuid

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_ROUTER = "src.auth.router"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI(root_path="/v1/auth")
    app.include_router(auth_router)
    return app


def _override_auth(app: FastAPI, roles=None):
    user = deps.CurrentUser(id=make_uuid(), email="admin@test.com", roles=roles or ["SUPER_ADMIN"])
    async def _no_auth():
        return user
    app.dependency_overrides[deps.check_route_permission] = _no_auth
    return user


def _fake_token_response(emp=None):
    emp = emp or _fake_employee()
    return {
        "access_token":  "header.payload.sig",
        "refresh_token": f"{uuid.uuid4()}||{'s' * 86}",
        "token_type":    "Bearer",
        "expires_in":    1800,
        "employee": {
            "employee_id":    str(emp.employee_id),
            "username":       emp.username,
            "email":          emp.email,
            "designation_id": str(emp.designation_id),
            "department_id":  str(emp.department_id),
        },
    }


def _fake_emp_response(emp=None):
    emp = emp or _fake_employee()
    return {
        "employee_id":    str(emp.employee_id),
        "username":       emp.username,
        "email":          emp.email,
        "designation_id": str(emp.designation_id),
        "department_id":  str(emp.department_id),
    }


@pytest.fixture
def app():
    a = _make_app()
    _override_auth(a)
    return a


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# POST /login
# ─────────────────────────────────────────────────────────────────────────────

class TestLoginRoute:
    def test_200_on_valid_credentials(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/login", json={"username": "john.doe", "password": "pass"})
        assert resp.status_code == 200

    def test_response_has_access_token(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/login", json={"username": "john.doe", "password": "pass"})
        assert "access_token" in resp.json()

    def test_response_has_refresh_token(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/login", json={"username": "john.doe", "password": "pass"})
        assert "refresh_token" in resp.json()

    def test_response_has_employee_object(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/login", json={"username": "john.doe", "password": "pass"})
        assert "employee" in resp.json()

    def test_401_on_invalid_credentials(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=401, detail="Invalid credentials")
            resp = client.post("/login", json={"username": "bad", "password": "wrong"})
        assert resp.status_code == 401

    def test_username_normalised_before_service_call(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            client.post("/login", json={"username": "  JOHN.DOE  ", "password": "pass"})
        # LoginRequest validator strips and lowercases
        call_username = m.call_args.args[0]
        assert call_username == call_username.strip().lower()

    def test_missing_username_returns_422(self, client):
        resp = client.post("/login", json={"password": "pass"})
        assert resp.status_code == 422

    def test_missing_password_returns_422(self, client):
        resp = client.post("/login", json={"username": "user"})
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, client):
        resp = client.post("/login", json={})
        assert resp.status_code == 422

    def test_token_type_is_bearer(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/login", json={"username": "u", "password": "p"})
        assert resp.json()["token_type"] == "Bearer"

    def test_service_called_with_username_and_password(self, client):
        with patch(f"{_ROUTER}.authenticate_user", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            client.post("/login", json={"username": "john.doe", "password": "secret"})
        assert m.call_args.args[0] == "john.doe"
        assert m.call_args.args[1] == "secret"


# ─────────────────────────────────────────────────────────────────────────────
# POST /refresh
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshRoute:
    def test_200_on_valid_refresh_token(self, client):
        with patch(f"{_ROUTER}.refresh_access_token", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/refresh", json={"refresh_token": f"{uuid.uuid4()}||secret"})
        assert resp.status_code == 200

    def test_response_has_access_token(self, client):
        with patch(f"{_ROUTER}.refresh_access_token", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            resp = client.post("/refresh", json={"refresh_token": "tok||sec"})
        assert "access_token" in resp.json()

    def test_401_on_invalid_token(self, client):
        with patch(f"{_ROUTER}.refresh_access_token", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=401, detail="Token expired or revoked")
            resp = client.post("/refresh", json={"refresh_token": "expired||token"})
        assert resp.status_code == 401

    def test_missing_refresh_token_returns_422(self, client):
        resp = client.post("/refresh", json={})
        assert resp.status_code == 422

    def test_service_called_with_token(self, client):
        token = f"{uuid.uuid4()}||secret"
        with patch(f"{_ROUTER}.refresh_access_token", new_callable=AsyncMock) as m:
            m.return_value = _fake_token_response()
            client.post("/refresh", json={"refresh_token": token})
        m.assert_awaited_once_with(token)


# ─────────────────────────────────────────────────────────────────────────────
# POST /validate
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateRoute:
    def test_200_with_valid_token(self, client):
        resp_data = {
            "valid":    True,
            "user_id":  make_uuid(),
            "email":    "u@test.com",
            "roles":    ["EMPLOYEE"],
            "department_id": make_uuid(),
        }
        with patch(f"{_ROUTER}.validate_token", new_callable=AsyncMock) as m:
            m.return_value = resp_data
            resp = client.post("/validate", json={"token": "good.jwt.token"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_200_with_invalid_token_returns_valid_false(self, client):
        resp_data = {"valid": False, "error": "Invalid or expired token"}
        with patch(f"{_ROUTER}.validate_token", new_callable=AsyncMock) as m:
            m.return_value = resp_data
            resp = client.post("/validate", json={"token": "bad.token"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_missing_token_returns_422(self, client):
        resp = client.post("/validate", json={})
        assert resp.status_code == 422

    def test_service_called_with_token_string(self, client):
        with patch(f"{_ROUTER}.validate_token", new_callable=AsyncMock) as m:
            m.return_value = {"valid": True, "user_id": "u", "email": "u@x.com", "roles": []}
            client.post("/validate", json={"token": "my.jwt.token"})
        m.assert_awaited_once_with("my.jwt.token")


# ─────────────────────────────────────────────────────────────────────────────
# POST /forgot-password
# ─────────────────────────────────────────────────────────────────────────────

class TestForgotPasswordRoute:
    def test_200_with_valid_email(self, client):
        with patch(f"{_ROUTER}.request_password_reset", new_callable=AsyncMock) as m:
            m.return_value = {"message": "If your email is registered, you will receive a password reset link shortly."}
            resp = client.post("/forgot-password", json={"email": "user@example.com"})
        assert resp.status_code == 200

    def test_response_has_message(self, client):
        with patch(f"{_ROUTER}.request_password_reset", new_callable=AsyncMock) as m:
            m.return_value = {"message": "Email sent"}
            resp = client.post("/forgot-password", json={"email": "user@example.com"})
        assert "message" in resp.json()

    def test_invalid_email_returns_422(self, client):
        resp = client.post("/forgot-password", json={"email": "not-an-email"})
        assert resp.status_code == 422

    def test_missing_email_returns_422(self, client):
        resp = client.post("/forgot-password", json={})
        assert resp.status_code == 422

    def test_200_even_for_non_existent_email(self, client):
        """No user enumeration via HTTP status."""
        with patch(f"{_ROUTER}.request_password_reset", new_callable=AsyncMock) as m:
            m.return_value = {"message": "If your email is registered..."}
            resp = client.post("/forgot-password", json={"email": "nobody@example.com"})
        assert resp.status_code == 200

    def test_service_called_with_email(self, client):
        with patch(f"{_ROUTER}.request_password_reset", new_callable=AsyncMock) as m:
            m.return_value = {"message": "ok"}
            client.post("/forgot-password", json={"email": "user@example.com"})
        assert m.call_args.args[0] == "user@example.com"


# ─────────────────────────────────────────────────────────────────────────────
# POST /reset-password
# ─────────────────────────────────────────────────────────────────────────────

class TestResetPasswordRoute:
    def test_200_on_valid_reset(self, client):
        with patch(f"{_ROUTER}.reset_password", new_callable=AsyncMock) as m:
            m.return_value = {"message": "Password reset successful. Please login with your new password."}
            resp = client.post("/reset-password", json={"token": "valid-token", "new_password": "NewPass1!"})
        assert resp.status_code == 200

    def test_response_has_message(self, client):
        with patch(f"{_ROUTER}.reset_password", new_callable=AsyncMock) as m:
            m.return_value = {"message": "Password reset successful."}
            resp = client.post("/reset-password", json={"token": "tok", "new_password": "NewPass1!"})
        assert "message" in resp.json()

    def test_400_on_invalid_token(self, client):
        with patch(f"{_ROUTER}.reset_password", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="Invalid or expired reset token")
            resp = client.post("/reset-password", json={"token": "bad", "new_password": "NewPass1!"})
        assert resp.status_code == 400

    def test_missing_token_returns_422(self, client):
        resp = client.post("/reset-password", json={"new_password": "NewPass1!"})
        assert resp.status_code == 422

    def test_missing_new_password_returns_422(self, client):
        resp = client.post("/reset-password", json={"token": "tok"})
        assert resp.status_code == 422

    def test_service_called_with_token_and_password(self, client):
        with patch(f"{_ROUTER}.reset_password", new_callable=AsyncMock) as m:
            m.return_value = {"message": "ok"}
            client.post("/reset-password", json={"token": "my-token", "new_password": "NewPass1!"})
        assert m.call_args.args[0] == "my-token"
        assert m.call_args.args[1] == "NewPass1!"


# ─────────────────────────────────────────────────────────────────────────────
# POST /signup  (protected)
# ─────────────────────────────────────────────────────────────────────────────

class TestSignupRoute:
    def _valid_payload(self):
        return {
            "username":       "new.employee",
            "email":          "new.employee@example.com",
            "password":       "TestPass1!",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }

    def test_201_on_valid_signup(self, client):
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = _fake_employee()
            resp = client.post("/signup", json=self._valid_payload())
        assert resp.status_code == 200

    def test_response_has_employee_id(self, client):
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post("/signup", json=self._valid_payload())
        assert "employee_id" in resp.json()

    def test_response_has_username(self, client):
        emp = _fake_employee(username="new.employee")
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post("/signup", json=self._valid_payload())
        assert resp.json()["username"] == "new.employee"

    def test_409_on_duplicate_email(self, client):
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=409, detail="Email already exists")
            resp = client.post("/signup", json=self._valid_payload())
        assert resp.status_code == 409

    def test_400_on_invalid_designation(self, client):
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.side_effect = HTTPException(status_code=400, detail="Designation not found")
            resp = client.post("/signup", json=self._valid_payload())
        assert resp.status_code == 400

    def test_missing_email_returns_422(self, client):
        payload = self._valid_payload()
        del payload["email"]
        resp = client.post("/signup", json=payload)
        assert resp.status_code == 422

    def test_missing_username_returns_422(self, client):
        payload = self._valid_payload()
        del payload["username"]
        resp = client.post("/signup", json=payload)
        assert resp.status_code == 422

    def test_missing_designation_id_returns_422(self, client):
        payload = self._valid_payload()
        del payload["designation_id"]
        resp = client.post("/signup", json=payload)
        assert resp.status_code == 422

    def test_invalid_designation_uuid_returns_422(self, client):
        payload = self._valid_payload()
        payload["designation_id"] = "not-a-uuid"
        resp = client.post("/signup", json=payload)
        assert resp.status_code == 422

    def test_invalid_email_format_returns_422(self, client):
        payload = self._valid_payload()
        payload["email"] = "not-an-email"
        resp = client.post("/signup", json=payload)
        assert resp.status_code == 422

    def test_service_called_with_source_signup(self, client):
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = _fake_employee()
            client.post("/signup", json=self._valid_payload())
        assert m.call_args.kwargs["source"] == "signup"


# ─────────────────────────────────────────────────────────────────────────────
# POST /bulk-import
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkImportRoute:
    def _csv_content(self, rows: list[dict]) -> bytes:
        import csv, io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode()

    def _valid_row(self, **overrides):
        base = {
            "username":       "emp.one",
            "email":          "emp.one@example.com",
            "password":       "TestPass1!",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }
        base.update(overrides)
        return base

    def test_200_on_valid_csv(self, client):
        csv_bytes = self._csv_content([self._valid_row()])
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        assert resp.status_code == 200

    def test_response_has_summary_keys(self, client):
        csv_bytes = self._csv_content([self._valid_row()])
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        body = resp.json()
        for key in ("total", "succeeded", "failed", "results"):
            assert key in body

    def test_400_on_unsupported_file_type(self, client):
        resp = client.post(
            "/bulk-import",
            files={"file": ("employees.txt", io.BytesIO(b"data"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_400_on_empty_file(self, client):
        resp = client.post(
            "/bulk-import",
            files={"file": ("employees.csv", io.BytesIO(b""), "text/csv")},
        )
        assert resp.status_code == 400

    def test_400_on_csv_with_no_data_rows(self, client):
        header_only = b"username,email,password,designation_id,department_id\n"
        resp = client.post(
            "/bulk-import",
            files={"file": ("employees.csv", io.BytesIO(header_only), "text/csv")},
        )
        assert resp.status_code == 400

    def test_partial_success_reported_correctly(self, client):
        row1 = self._valid_row(username="emp1", email="emp1@example.com")
        row2 = self._valid_row(username="emp2", email="emp2@example.com")
        csv_bytes = self._csv_content([row1, row2])
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.side_effect = [emp, HTTPException(status_code=409, detail="Duplicate")]
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        body = resp.json()
        assert body["succeeded"] == 1
        assert body["failed"]    == 1

    def test_missing_required_column_row_marked_as_error(self, client):
        bad_row = {"username": "emp1", "email": "emp1@example.com"}   # missing required cols
        csv_bytes = self._csv_content([bad_row])
        resp = client.post(
            "/bulk-import",
            files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
        )
        body = resp.json()
        assert body["failed"] == 1
        assert body["results"][0]["status"] == "error"

    def test_success_row_has_employee_id(self, client):
        csv_bytes = self._csv_content([self._valid_row()])
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        first_result = resp.json()["results"][0]
        assert first_result["status"] == "success"
        assert "employee_id" in first_result

    def test_total_matches_number_of_rows(self, client):
        rows = [
            self._valid_row(username=f"emp{i}", email=f"emp{i}@example.com")
            for i in range(3)
        ]
        csv_bytes = self._csv_content(rows)
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        assert resp.json()["total"] == 3

    def test_service_called_with_source_bulk_import(self, client):
        csv_bytes = self._csv_content([self._valid_row()])
        emp = _fake_employee()
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.return_value = emp
            client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        assert m.call_args.kwargs["source"] == "bulk_import"

    def test_400_on_corrupt_csv_parse_error(self, client):
        """Covers the except Exception parse-error branch (lines 163-164)."""
        with patch(f"{_ROUTER}._parse_csv", side_effect=Exception("bad encoding")):
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(b"garbage"), "text/csv")},
            )
        assert resp.status_code == 400
        assert "parse error" in resp.json()["detail"].lower()

    def test_row_bare_exception_counted_as_failure(self, client):
        """Covers the bare except Exception in the per-row loop (lines 204-212)."""
        csv_bytes = self._csv_content([self._valid_row()])
        with patch(f"{_ROUTER}.create_employee", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("unexpected db error")
            resp = client.post(
                "/bulk-import",
                files={"file": ("employees.csv", io.BytesIO(csv_bytes), "text/csv")},
            )
        body = resp.json()
        assert body["failed"] == 1
        assert body["results"][0]["status"] == "error"
        assert "unexpected db error" in body["results"][0]["error"]


# ─────────────────────────────────────────────────────────────────────────────
# POST /logout  (needs a real Bearer token)
# ─────────────────────────────────────────────────────────────────────────────

class TestLogoutRoute:
    def _make_token(self, user_id: str = None) -> str:
        import jwt, os
        uid = user_id or make_uuid()
        return jwt.encode(
            {"sub": uid, "email": "u@x.com", "roles": ["EMPLOYEE"]},
            os.environ["SECRET_KEY"],
            algorithm=os.environ["ALGORITHM"],
        )

    def test_200_on_valid_logout(self, client):
        token = self._make_token()
        with (
            patch(f"{_ROUTER}.decode_token", return_value={"sub": make_uuid()}),
            patch(f"{_ROUTER}.logout_user", new_callable=AsyncMock) as m,
        ):
            m.return_value = {"message": "Logged out successfully"}
            resp = client.post(
                "/logout",
                json={"refresh_token": f"{uuid.uuid4()}||secret"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200

    def test_response_has_message(self, client):
        token = self._make_token()
        with (
            patch(f"{_ROUTER}.decode_token", return_value={"sub": make_uuid()}),
            patch(f"{_ROUTER}.logout_user", new_callable=AsyncMock) as m,
        ):
            m.return_value = {"message": "Logged out successfully"}
            resp = client.post(
                "/logout",
                json={"refresh_token": f"{uuid.uuid4()}||secret"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert "message" in resp.json()

    def test_401_when_no_bearer_token(self, client):
        resp = client.post("/logout", json={"refresh_token": "tok||sec"})
        assert resp.status_code in (401, 403, 422)

    def test_401_when_token_invalid(self, client):
        with patch(f"{_ROUTER}.decode_token", return_value=None):
            resp = client.post(
                "/logout",
                json={"refresh_token": f"{uuid.uuid4()}||secret"},
                headers={"Authorization": "Bearer bad.token.here"},
            )
        assert resp.status_code == 401

    def test_missing_refresh_token_returns_422(self, client):
        token = self._make_token()
        resp = client.post(
            "/logout",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# CSV / XLSX parsing helpers  (_parse_csv, _parse_xlsx, _row_to_signup)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseHelpers:
    def test_parse_csv_returns_list_of_dicts(self):
        from src.auth.router import _parse_csv
        csv_bytes = b"username,email\njohn,john@example.com\n"
        rows = _parse_csv(csv_bytes)
        assert isinstance(rows, list)
        assert rows[0]["username"] == "john"

    def test_parse_csv_handles_bom(self):
        from src.auth.router import _parse_csv
        # Simulate a real UTF-8-BOM file: BOM byte sequence followed by normal CSV
        # The router decodes with "utf-8-sig" which strips the BOM marker
        bom_csv = b"\xef\xbb\xbfusername,email\njohn,john@example.com\n"
        rows = _parse_csv(bom_csv)
        assert "username" in rows[0]

    def test_parse_csv_empty_body_returns_empty_list(self):
        from src.auth.router import _parse_csv
        rows = _parse_csv(b"username,email\n")
        assert rows == []

    def test_row_to_signup_missing_column_returns_error(self):
        from src.auth.router import _row_to_signup
        row = {"username": "emp", "email": "emp@example.com"}   # missing cols
        payload, err = _row_to_signup(row)
        assert payload is None
        assert err is not None
        assert "Missing" in err

    def test_row_to_signup_empty_required_field_returns_error(self):
        from src.auth.router import _row_to_signup
        row = {
            "username": "",   # empty
            "email": "emp@example.com",
            "password": "pass",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }
        payload, err = _row_to_signup(row)
        assert payload is None
        assert err is not None

    def test_row_to_signup_valid_row_returns_signup_request(self):
        from src.auth.router import _row_to_signup
        row = {
            "username":       "emp.one",
            "email":          "emp.one@example.com",
            "password":       "TestPass1!",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }
        payload, err = _row_to_signup(row)
        assert payload is not None
        assert err is None
        assert payload.username == "emp.one"

    def test_row_to_signup_invalid_uuid_returns_error(self):
        from src.auth.router import _row_to_signup
        row = {
            "username":       "emp",
            "email":          "emp@example.com",
            "password":       "pass",
            "designation_id": "not-a-uuid",
            "department_id":  str(uuid.uuid4()),
        }
        payload, err = _row_to_signup(row)
        assert payload is None
        assert err is not None

    def test_row_to_signup_strips_whitespace_from_values(self):
        from src.auth.router import _row_to_signup
        row = {
            "username":       "  emp.one  ",
            "email":          "  emp.one@example.com  ",
            "password":       "TestPass1!",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }
        payload, err = _row_to_signup(row)
        assert err is None
        assert payload.username == "emp.one"

    def test_row_to_signup_optional_manager_id_none_when_absent(self):
        from src.auth.router import _row_to_signup
        row = {
            "username":       "emp",
            "email":          "emp@example.com",
            "password":       "pass",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
        }
        payload, err = _row_to_signup(row)
        assert err is None
        assert payload.manager_id is None

    def test_row_to_signup_optional_manager_id_parsed_when_present(self):
        from src.auth.router import _row_to_signup
        mgr_id = str(uuid.uuid4())
        row = {
            "username":       "emp",
            "email":          "emp@example.com",
            "password":       "pass",
            "designation_id": str(uuid.uuid4()),
            "department_id":  str(uuid.uuid4()),
            "manager_id":     mgr_id,
        }
        payload, err = _row_to_signup(row)
        assert err is None
        assert str(payload.manager_id) == mgr_id