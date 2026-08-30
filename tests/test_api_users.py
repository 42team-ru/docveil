from unittest.mock import AsyncMock
import uuid
import pytest
from fastapi import status
from datetime import datetime, UTC

from api.main import app
from api.core.deps import require_admin
from api.models.user import UserORM


@pytest.fixture
def admin_user():
    return UserORM(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="hash",
        full_name="Admin",
        roles=["admin"],
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def override_require_admin(admin_user):
    async def _mock_require_admin():
        return admin_user
    app.dependency_overrides[require_admin] = _mock_require_admin
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def mock_user_service(mocker):
    mocker.patch("api.routers.users.email_exists", new_callable=AsyncMock)
    mocker.patch("api.routers.users.create_user", new_callable=AsyncMock)
    mocker.patch("api.routers.users.list_users", new_callable=AsyncMock)
    return mocker


def test_create_user_success(client, override_require_admin, mock_user_service):
    user_id = uuid.uuid4()
    mock_user_service.patch("api.routers.users.email_exists").return_value = False
    
    created_user = UserORM(
        id=user_id,
        email="newuser@example.com",
        password_hash="hash",
        full_name="New User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    mock_user_service.patch("api.routers.users.create_user").return_value = created_user

    response = client.post(
        "/api/users",
        json={"email": "newuser@example.com", "password": "password123", "full_name": "New User", "roles": ["user"]},
    )
    
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["id"] == str(user_id)


def test_create_user_email_exists(client, override_require_admin, mock_user_service):
    mock_user_service.patch("api.routers.users.email_exists").return_value = True

    response = client.post(
        "/api/users",
        json={"email": "newuser@example.com", "password": "password123", "full_name": "New User", "roles": ["user"]},
    )
    
    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"] == "Пользователь с таким email уже существует"


def test_list_users(client, override_require_admin, mock_user_service, admin_user):
    mock_user_service.patch("api.routers.users.list_users").return_value = [admin_user]

    response = client.get("/api/users")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["email"] == "admin@example.com"


def test_create_user_unauthorized_without_token(client, mock_user_service):
    response = client.post(
        "/api/users",
        json={"email": "newuser@example.com", "password": "password123", "full_name": "New User"},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_users_unauthorized_without_token(client, mock_user_service):
    response = client.get("/api/users")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_create_user_forbidden_for_non_admin(client, mock_user_service):
    from api.core.deps import get_current_user

    non_admin = UserORM(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hash",
        full_name="Regular User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    async def _mock_get_current_user():
        return non_admin

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    try:
        response = client.post(
            "/api/users",
            json={"email": "newuser@example.com", "password": "password123", "full_name": "New User"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_create_user_missing_fields_returns_422(client, override_require_admin):
    response = client.post("/api/users", json={"email": "no-password@example.com"})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
