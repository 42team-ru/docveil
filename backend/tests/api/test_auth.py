import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

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

    client.cookies.set("refresh_token", "old_refresh_token")
    response = client.post("/api/auth/refresh")

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

    client.cookies.set("refresh_token", "invalid_refresh_token")
    response = client.post("/api/auth/refresh")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Невалидный или просроченный refresh-токен"


def test_logout(client, mock_auth_service):
    mock_revoke = mock_auth_service.patch("api.routers.auth.revoke_refresh_token")

    client.cookies.set("refresh_token", "token_to_revoke")
    response = client.post("/api/auth/logout")

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


def _override_current_user(user: UserORM):
    async def _mock_get_current_user():
        return user

    app.dependency_overrides[get_current_user] = _mock_get_current_user


def test_update_me_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Old Name",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    updated = UserORM(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        full_name="New Name",
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
    )
    mock_update = mocker.patch(
        "api.routers.auth.update_profile", new_callable=AsyncMock
    )
    mock_update.return_value = updated

    _override_current_user(user)
    try:
        response = client.patch("/api/auth/me", json={"full_name": "New Name"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["full_name"] == "New Name"
    mock_update.assert_awaited_once()


def test_update_me_unauthorized_without_token(client):
    response = client.patch("/api/auth/me", json={"full_name": "New Name"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_change_my_password_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    mock_change = mocker.patch(
        "api.routers.auth.change_password", new_callable=AsyncMock
    )

    _override_current_user(user)
    try:
        response = client.post(
            "/api/auth/me/password",
            json={"current_password": "old-pass", "new_password": "new-pass"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_change.assert_awaited_once()


def test_change_my_password_wrong_current_password(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    mock_change = mocker.patch(
        "api.routers.auth.change_password", new_callable=AsyncMock
    )
    mock_change.side_effect = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Неверный текущий пароль"
    )

    _override_current_user(user)
    try:
        response = client.post(
            "/api/auth/me/password",
            json={"current_password": "wrong-pass", "new_password": "new-pass"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Неверный текущий пароль"


def test_change_my_password_unauthorized_without_token(client):
    response = client.post(
        "/api/auth/me/password",
        json={"current_password": "old-pass", "new_password": "new-pass"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_update_me_timezone_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    updated = UserORM(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        full_name=user.full_name,
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
        timezone="Europe/Moscow",
    )
    mock_update = mocker.patch(
        "api.routers.auth.update_profile", new_callable=AsyncMock
    )
    mock_update.return_value = updated

    _override_current_user(user)
    try:
        response = client.patch("/api/auth/me", json={"timezone": "Europe/Moscow"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["timezone"] == "Europe/Moscow"


def test_update_me_rejects_unknown_timezone(client):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    _override_current_user(user)
    try:
        response = client.patch("/api/auth/me", json={"timezone": "Mars/Olympus_Mons"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_upload_my_avatar_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    updated = UserORM(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        full_name=user.full_name,
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
        avatar_object_name="abc123/photo.png",
    )
    mocker.patch(
        "api.routers.auth.upload_file",
        new_callable=AsyncMock,
        return_value=("abc123/photo.png", 1234),
    )
    mock_set = mocker.patch(
        "api.routers.auth.set_avatar", new_callable=AsyncMock
    )
    mock_set.return_value = updated

    _override_current_user(user)
    try:
        response = client.post(
            "/api/auth/me/avatar",
            files={"file": ("photo.png", b"fake-bytes", "image/png")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_avatar"] is True


def test_upload_my_avatar_rejects_non_image(client):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    _override_current_user(user)
    try:
        response = client.post(
            "/api/auth/me/avatar",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_get_my_avatar_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
        avatar_object_name="abc123/photo.png",
    )
    mocker.patch("api.routers.auth.download_file", return_value=b"fake-bytes")

    _override_current_user(user)
    try:
        response = client.get("/api/auth/me/avatar")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.content == b"fake-bytes"
    assert response.headers["content-type"] == "image/png"


def test_get_my_avatar_not_found(client):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    _override_current_user(user)
    try:
        response = client.get("/api/auth/me/avatar")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_delete_my_avatar_success(client, mocker):
    user = UserORM(
        id=uuid.uuid4(),
        email="me@example.com",
        password_hash="hash",
        full_name="Me User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
        avatar_object_name="abc123/photo.png",
    )
    updated = UserORM(
        id=user.id,
        email=user.email,
        password_hash=user.password_hash,
        full_name=user.full_name,
        roles=user.roles,
        is_active=user.is_active,
        created_at=user.created_at,
        avatar_object_name=None,
    )
    mock_clear = mocker.patch(
        "api.routers.auth.clear_avatar", new_callable=AsyncMock
    )
    mock_clear.return_value = updated

    _override_current_user(user)
    try:
        response = client.delete("/api/auth/me/avatar")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["has_avatar"] is False
