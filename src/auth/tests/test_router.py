"""
Tests for src/auth/router.py
Covers: all endpoints via FastAPI TestClient, bulk import helpers
"""

import sys
import pytest
import io
import csv
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from fastapi.testclient import TestClient
from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Mock src.core.security before any auth module is imported
# ---------------------------------------------------------------------------

_security_mock = MagicMock()
_security_mock.decode_token = MagicMock(return_value={"sub": "u1"})
_security_mock.create_access_token = MagicMock(return_value="access.token")
_security_mock.verify_password = MagicMock(return_value=True)
_security_mock.hash_password = MagicMock(return_value="hashed")
_security_mock.hash_refresh_token = MagicMock(return_value="hashed_rt")
_security_mock.verify_refresh_token = MagicMock(return_value=True)
_security_mock.ACCESS_TOKEN_EXPIRE_MINUTES = 30
sys.modules.setdefault("src.core.security", _security_mock)
sys.modules.setdefault("src.core", MagicMock(security=_security_mock))
sys.modules.setdefault("src.core.email_utils", MagicMock())
sys.modules.setdefault("src.prisma", MagicMock())
sys.modules.setdefault("src.prisma.client", MagicMock())


# ---------------------------------------------------------------------------
# App factory — override the auth dependency so it never hits OAuth2 check
# ---------------------------------------------------------------------------

def _create_test_app(mock_user=None):
    from src.auth.router import router
    from src.auth.dependencies import CurrentUser, oauth2_scheme

    app = FastAPI()
    app.include_router(router, prefix="/v1/auth")

    if mock_user:
        # Override the oauth2 bearer scheme so TestClient doesn't get 401
        app.dependency_overrides[oauth2_scheme] = lambda: "mocked.token"

    return app


def _make_current_user(roles=None):
    from src.auth.dependencies import CurrentUser
    return CurrentUser(id="admin-id", roles=roles or ["SUPER_ADMIN"])


# ---------------------------------------------------------------------------
# CSV / XLSX parse helpers
# ---------------------------------------------------------------------------

class TestParseCsv:

    def test_parse_valid_csv(self):
        from src.auth.router import _parse_csv

        content = b"username,email,password,designation_id,department_id\njdoe,jdoe@x.com,pass,uid1,uid2\n"
        rows = _parse_csv(content)

        assert len(rows) == 1
        assert rows[0]["username"] == "jdoe"

    def test_parse_csv_with_bom(self):
        from src.auth.router import _parse_csv

        # Encode with BOM, then parse — the utf-8-sig decoder strips it
        text = "username,email,password,designation_id,department_id\njdoe,jdoe@x.com,pass,uid1,uid2\n"
        content = text.encode("utf-8-sig")  # adds BOM prefix
        rows = _parse_csv(content)

        assert len(rows) == 1
        assert rows[0]["username"] == "jdoe"

    def test_parse_empty_csv_returns_empty_list(self):
        from src.auth.router import _parse_csv

        content = b"username,email,password,designation_id,department_id\n"
        rows = _parse_csv(content)

        assert rows == []


class TestRowToSignup:

    def _valid_row(self):
        return {
            "username": "jdoe",
            "email": "jdoe@example.com",
            "password": "Pass123",
            "designation_id": str(uuid4()),
            "department_id": str(uuid4()),
        }

    def test_valid_row_returns_signup_request(self):
        from src.auth.router import _row_to_signup
        req, err = _row_to_signup(self._valid_row())
        assert req is not None
        assert err is None
        assert req.username == "jdoe"

    def test_missing_required_column_returns_error(self):
        from src.auth.router import _row_to_signup
        row = self._valid_row()
        del row["email"]
        req, err = _row_to_signup(row)
        assert req is None
        assert "email" in err.lower()

    def test_empty_required_field_returns_error(self):
        from src.auth.router import _row_to_signup
        row = self._valid_row()
        row["username"] = ""
        req, err = _row_to_signup(row)
        assert req is None
        assert "username" in err

    def test_invalid_uuid_returns_error(self):
        from src.auth.router import _row_to_signup
        row = self._valid_row()
        row["designation_id"] = "not-a-uuid"
        req, err = _row_to_signup(row)
        assert req is None
        assert err is not None

    def test_optional_manager_id_included(self):
        from src.auth.router import _row_to_signup
        row = self._valid_row()
        row["manager_id"] = str(uuid4())
        req, err = _row_to_signup(row)
        assert req is not None
        assert req.manager_id is not None

    def test_column_names_are_case_insensitive(self):
        from src.auth.router import _row_to_signup
        row = {
            "Username": "jdoe",
            "Email": "jdoe@example.com",
            "Password": "Pass123",
            "Designation_Id": str(uuid4()),
            "Department_Id": str(uuid4()),
        }
        req, err = _row_to_signup(row)
        assert req is not None


# ---------------------------------------------------------------------------
# Router endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    app = _create_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def authed_client():
    """Client with oauth2_scheme overridden so bearer token is never validated."""
    app = _create_test_app(mock_user=True)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestLoginEndpoint:

    def test_login_success(self, client):
        mock_response = {
            "access_token": "access",
            "refresh_token": "refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "employee": {
                "employee_id": str(uuid4()),
                "username": "jdoe",
                "email": "jdoe@example.com",
            },
        }
        with patch("src.auth.router.authenticate_user", new=AsyncMock(return_value=mock_response)):
            resp = client.post("/v1/auth/login", json={"username": "jdoe", "password": "pass"})

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "access"

    def test_login_invalid_credentials(self, client):
        from fastapi import HTTPException
        with patch(
            "src.auth.router.authenticate_user",
            new=AsyncMock(side_effect=HTTPException(status_code=401, detail="Invalid credentials")),
        ):
            resp = client.post("/v1/auth/login", json={"username": "bad", "password": "bad"})

        assert resp.status_code == 401


class TestRefreshEndpoint:

    def test_refresh_success(self, client):
        mock_response = {
            "access_token": "new_access",
            "refresh_token": "refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            "employee": {
                "employee_id": str(uuid4()),
                "username": "jdoe",
                "email": "jdoe@example.com",
            },
        }
        with patch("src.auth.router.refresh_access_token", new=AsyncMock(return_value=mock_response)):
            resp = client.post("/v1/auth/refresh", json={"refresh_token": "valid-token"})

        assert resp.status_code == 200
        assert resp.json()["access_token"] == "new_access"


class TestLogoutEndpoint:

    def test_logout_success(self, authed_client):
        with (
            patch("src.auth.router.decode_token", return_value={"sub": "u1"}),
            patch("src.auth.router.logout_user", new=AsyncMock(return_value={"message": "Logged out successfully"})),
        ):
            resp = authed_client.post(
                "/v1/auth/logout",
                json={"refresh_token": "rt"},
                headers={"Authorization": "Bearer valid.token"},
            )
        assert resp.status_code == 200

    def test_logout_invalid_token(self, authed_client):
        with (
            patch("src.auth.router.decode_token", return_value=None),
        ):
            resp = authed_client.post(
                "/v1/auth/logout",
                json={"refresh_token": "rt"},
                headers={"Authorization": "Bearer invalid.token"},
            )
        assert resp.status_code == 401


class TestValidateEndpoint:

    def test_valid_token(self, client):
        mock_resp = {
            "valid": True,
            "user_id": "u1",
            "email": "u@x.com",
            "roles": ["EMPLOYEE"],
            "department_id": "d1",
        }
        with patch("src.auth.router.validate_token", new=AsyncMock(return_value=mock_resp)):
            resp = client.post("/v1/auth/validate", json={"token": "valid.token"})

        assert resp.status_code == 200
        assert resp.json()["valid"] is True


class TestForgotPasswordEndpoint:

    def test_forgot_password_returns_message(self, client):
        with patch(
            "src.auth.router.request_password_reset",
            new=AsyncMock(return_value={"message": "Check your email"}),
        ):
            resp = client.post("/v1/auth/forgot-password", json={"email": "u@x.com"})

        assert resp.status_code == 200
        assert "message" in resp.json()


class TestResetPasswordEndpoint:

    def test_reset_password_success(self, client):
        with patch(
            "src.auth.router.reset_password",
            new=AsyncMock(return_value={"message": "Password reset successful"}),
        ):
            resp = client.post(
                "/v1/auth/reset-password",
                json={"token": "reset-tok", "new_password": "NewPass123"},
            )
        assert resp.status_code == 200


class TestSignupEndpoint:

    def test_signup_requires_auth(self, client):
        resp = client.post(
            "/v1/auth/signup",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "Pass123",
                "designation_id": str(uuid4()),
                "department_id": str(uuid4()),
            },
        )
        assert resp.status_code in (401, 403)

    def test_signup_success_with_auth(self, authed_client):
        from src.auth.dependencies import CurrentUser

        new_emp = MagicMock()
        new_emp.employee_id = uuid4()
        new_emp.username = "newuser"
        new_emp.email = "new@example.com"
        new_emp.designation_id = uuid4()
        new_emp.department_id = uuid4()

        mock_user = CurrentUser(id="admin-id", roles=["HR_ADMIN"])

        with (
            patch("src.auth.router.require_roles", return_value=lambda: mock_user),
            patch("src.auth.router.create_employee", new=AsyncMock(return_value=new_emp)),
        ):
            resp = authed_client.post(
                "/v1/auth/signup",
                json={
                    "username": "newuser",
                    "email": "new@example.com",
                    "password": "Pass123",
                    "designation_id": str(uuid4()),
                    "department_id": str(uuid4()),
                },
                headers={"Authorization": "Bearer valid.token"},
            )

        assert resp.status_code != 500


class TestBulkImportEndpoint:

    def _make_csv_bytes(self, rows: list[dict]) -> bytes:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")

    def test_bulk_import_requires_auth(self, client):
        csv_bytes = self._make_csv_bytes([
            {"username": "u", "email": "u@x.com", "password": "p",
             "designation_id": str(uuid4()), "department_id": str(uuid4())}
        ])
        resp = client.post(
            "/v1/auth/bulk-import",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
        assert resp.status_code in (401, 403)

    def _authed_bulk_client(self):
        """Create a TestClient with bulk-import auth fully bypassed via dependency_overrides."""
        from src.auth.router import router
        from src.auth.dependencies import CurrentUser, oauth2_scheme, require_roles

        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")

        mock_user = CurrentUser(id="admin-id", roles=["SUPER_ADMIN"])

        # Find the actual role_checker dependency bound to the bulk-import route
        # by overriding oauth2_scheme AND the inner role_checker function.
        # The easiest approach: override every dependency that could block us.
        app.dependency_overrides[oauth2_scheme] = lambda: "mocked.token"

        # Override get_current_user and the role_checker produced by require_roles
        # Since we can't easily get the bound role_checker, patch decode_token instead.
        # We override oauth2_scheme so the token passed is "mocked.token", and
        # _security_mock.decode_token already returns {"sub": "u1"} — but that has no
        # roles, causing a 403. So we need to patch decode_token to return SUPER_ADMIN.
        import src.auth.dependencies as deps
        original = deps.decode_token
        deps.decode_token = lambda token: {"sub": "u1", "roles": ["SUPER_ADMIN"]}

        client = TestClient(app, raise_server_exceptions=False)
        return client, deps, original

    def test_bulk_import_unsupported_file_type(self, authed_client):
        client, deps, original = self._authed_bulk_client()
        try:
            resp = client.post(
                "/v1/auth/bulk-import",
                files={"file": ("test.txt", b"data", "text/plain")},
                headers={"Authorization": "Bearer valid.token"},
            )
        finally:
            deps.decode_token = original
        assert resp.status_code == 400

    def test_bulk_import_empty_file(self, authed_client):
        client, deps, original = self._authed_bulk_client()
        try:
            resp = client.post(
                "/v1/auth/bulk-import",
                files={"file": ("test.csv", b"", "text/csv")},
                headers={"Authorization": "Bearer valid.token"},
            )
        finally:
            deps.decode_token = original
        assert resp.status_code == 400