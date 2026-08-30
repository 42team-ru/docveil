import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from api.core.deps import get_current_user
from api.main import app
from api.models.user import UserORM


@pytest.fixture
def mock_auth_service(mocker):
    mocker.patch("api.routers.auth.authenticate_user", new_callable=AsyncMock)
    mocker.patch("api.routers.auth.issue_tokens", new_callable=AsyncMock)
    mocker.patch("api.routers.auth.rotate_refresh_token", new_callable=AsyncMock)
    mocker.patch("api.routers.auth.revoke_refresh_token", new_callable=AsyncMock)
    return mocker


def test_login_success_web(client, mock_auth_service):
    user = UserORM(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="hash",
        full_name="Test User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    mock_auth_service.patch("api.routers.auth.authenticate_user").return_value = user
    expires_at = datetime.now(UTC) + timedelta(days=30)
    mock_auth_service.patch("api.routers.auth.issue_tokens").return_value = (
        "access_token123",
        "refresh_token456",
        expires_at,
    )

    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password", "device": "web"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "access_token": "access_token123",
        "token_type": "bearer",
        "refresh_token": None,
    }
    assert "refresh_token" in response.cookies
    assert response.cookies["refresh_token"] == "refresh_token456"


def test_login_success_mobile(client, mock_auth_service):
    user = UserORM(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="hash",
        full_name="Test User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    mock_auth_service.patch("api.routers.auth.authenticate_user").return_value = user
    expires_at = datetime.now(UTC) + timedelta(days=30)
    mock_auth_service.patch("api.routers.auth.issue_tokens").return_value = (
        "access_token123",
        "refresh_token456",
        expires_at,
    )

    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "password", "device": "mobile"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "access_token": "access_token123",
        "token_type": "bearer",
        "refresh_token": "refresh_token456",
    }
    assert "refresh_token" not in response.cookies


def test_login_invalid_credentials(client, mock_auth_service):
    mock_auth_service.patch("api.routers.auth.authenticate_user").return_value = None

    response = client.post(
        "/api/auth/login",
        json={"email": "test@example.com", "password": "wrong_password", "device": "web"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Неверный email или пароль"


def test_refresh_success_cookie(client, mock_auth_service):
    user = UserORM(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="hash",
        full_name="Test User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    expires_at = datetime.now(UTC) + timedelta(days=30)
    mock_auth_service.patch("api.routers.auth.rotate_refresh_token").return_value = (
        user,
        "new_access",
        "new_refresh",
        expires_at,
    )

    response = client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": "old_refresh_token"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "access_token": "new_access",
        "token_type": "bearer",
        "refresh_token": None,
    }
    assert response.cookies["refresh_token"] == "new_refresh"


def test_refresh_success_body(client, mock_auth_service):
    user = UserORM(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="hash",
        full_name="Test User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    expires_at = datetime.now(UTC) + timedelta(days=30)
    mock_auth_service.patch("api.routers.auth.rotate_refresh_token").return_value = (
        user,
        "new_access",
        "new_refresh",
        expires_at,
    )

    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "old_refresh_token"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "access_token": "new_access",
        "token_type": "bearer",
        "refresh_token": "new_refresh",
    }


def test_refresh_missing_token(client):
    response = client.post("/api/auth/refresh")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Refresh-токен не передан"


def test_refresh_invalid_token(client, mock_auth_service):
    mock_auth_service.patch("api.routers.auth.rotate_refresh_token").return_value = None

    response = client.post(
        "/api/auth/refresh",
        cookies={"refresh_token": "invalid_refresh_token"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Невалидный или просроченный refresh-токен"


def test_logout(client, mock_auth_service):
    mock_revoke = mock_auth_service.patch("api.routers.auth.revoke_refresh_token")

    response = client.post(
        "/api/auth/logout",
        cookies={"refresh_token": "token_to_revoke"},
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_revoke.assert_called_once()
    assert "set-cookie" in response.headers
    assert "refresh_token" in response.headers["set-cookie"]
    assert (
        "Max-Age=0" in response.headers["set-cookie"]
        or "expires" in response.headers["set-cookie"].lower()
    )


def test_logout_without_token_does_not_call_revoke(client, mock_auth_service):
    mock_revoke = mock_auth_service.patch("api.routers.auth.revoke_refresh_token")

    response = client.post("/api/auth/logout")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_revoke.assert_not_called()


def test_me_success(client):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    async def _mock_get_current_user():
        return user

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    try:
        response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["email"] == "me@example.com"
    assert "password_hash" not in data


def test_me_unauthorized_without_token(client):
    response = client.get("/api/auth/me")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Не авторизован"


def test_me_unauthorized_with_garbage_token(client):
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Невалидный или просроченный токен"
