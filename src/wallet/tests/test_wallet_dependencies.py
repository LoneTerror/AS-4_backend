# Ensures valid auth service response returns CurrentUser
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi import HTTPException
from src.wallet.dependencies import get_current_user


@pytest.mark.asyncio
@patch("src.wallet.dependencies.httpx.AsyncClient")
async def test_get_current_user_success(mock_client):
    # Mock HTTP response (sync json() method)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "valid": True,
        "user_id": "user-1",
        "email": "test@example.com",
        "roles": ["hr_admin"],
        "department_id": "dept-1"
    }

    # Mock async post() call
    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_response
    )

    request = Request(scope={"type": "http", "headers": []})
    credentials = type("Creds", (), {"credentials": "fake-token"})

    user = await get_current_user(request, credentials)

    assert user.id == "user-1"
    assert user.email == "test@example.com"
    assert "HR_ADMIN" in user.roles  # normalized to uppercase
    assert user.department_id == "dept-1"


# Ensures non-200 auth response raises 401
@pytest.mark.asyncio
@patch("src.wallet.dependencies.httpx.AsyncClient")
async def test_get_current_user_non_200(mock_client):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.json.return_value = {}

    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_response
    )

    request = Request(scope={"type": "http", "headers": []})
    credentials = type("Creds", (), {"credentials": "bad-token"})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials)

    assert exc.value.status_code == 401


# Ensures valid=False in auth response raises 401
@pytest.mark.asyncio
@patch("src.wallet.dependencies.httpx.AsyncClient")
async def test_get_current_user_invalid_flag(mock_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "valid": False
    }

    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
        return_value=mock_response
    )

    request = Request(scope={"type": "http", "headers": []})
    credentials = type("Creds", (), {"credentials": "bad-token"})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials)

    assert exc.value.status_code == 401


# Ensures auth service failure raises 503
@pytest.mark.asyncio
@patch("src.wallet.dependencies.httpx.AsyncClient")
async def test_get_current_user_request_error(mock_client):
    import httpx

    mock_client.return_value.__aenter__.return_value.post = AsyncMock(
        side_effect=httpx.RequestError("boom")
    )

    request = Request(scope={"type": "http", "headers": []})
    credentials = type("Creds", (), {"credentials": "token"})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(request, credentials)

    assert exc.value.status_code == 503


# Ensures SUPER_ADMIN bypasses role restriction
@pytest.mark.asyncio
async def test_require_roles_super_admin():
    from src.wallet.dependencies import require_roles, CurrentUser

    checker = require_roles("HR_ADMIN")

    user = CurrentUser(
        id="1",
        email="x@test.com",
        roles=["SUPER_ADMIN"]
    )

    result = await checker(user)

    assert result == user


# Ensures user with allowed role passes validation
@pytest.mark.asyncio
async def test_require_roles_allowed():
    from src.wallet.dependencies import require_roles, CurrentUser

    checker = require_roles("HR_ADMIN")

    user = CurrentUser(
        id="1",
        email="x@test.com",
        roles=["HR_ADMIN"]
    )

    result = await checker(user)

    assert result == user


# Ensures allowed roles are case-insensitive
@pytest.mark.asyncio
async def test_require_roles_case_insensitive():
    from src.wallet.dependencies import require_roles, CurrentUser

    checker = require_roles("hr_admin")

    user = CurrentUser(
        id="1",
        email="x@test.com",
        roles=["HR_ADMIN"]
    )

    result = await checker(user)

    assert result == user


# Ensures user without required role gets 403
@pytest.mark.asyncio
async def test_require_roles_forbidden():
    from src.wallet.dependencies import require_roles, CurrentUser

    checker = require_roles("HR_ADMIN")

    user = CurrentUser(
        id="1",
        email="x@test.com",
        roles=["EMPLOYEE"]
    )

    with pytest.raises(HTTPException) as exc:
        await checker(user)

    assert exc.value.status_code == 403