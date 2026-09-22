"""Роуты /admin/llm-profiles — доступ только администратору, тонкая обвязка сервиса."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from api.core.deps import require_admin
from api.main import app
from api.models.user import UserORM
from api.schemas.llm_profile import LLMProfileOut


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
def mock_service(mocker):
    mocker.patch(
        "api.routers.llm_profiles.llm_profile_service.list_profiles", new_callable=AsyncMock
    )
    mocker.patch(
        "api.routers.llm_profiles.llm_profile_service.create_profile", new_callable=AsyncMock
    )
    mocker.patch(
        "api.routers.llm_profiles.llm_profile_service.delete_profile", new_callable=AsyncMock
    )
    mocker.patch("api.routers.llm_profiles.llm_profile_service.set_active", new_callable=AsyncMock)
    return mocker


def test_list_requires_authorization(client, mock_service):
    assert client.get("/api/admin/llm-profiles").status_code == status.HTTP_401_UNAUTHORIZED


def test_list_forbidden_for_non_admin(client, mock_service):
    from api.core.deps import get_current_user

    non_admin = UserORM(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hash",
        full_name="Regular",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    async def _mock_get_current_user():
        return non_admin

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    try:
        response = client.get("/api/admin/llm-profiles")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_list_returns_service_output(client, override_require_admin, mock_service):
    mock_service.patch(
        "api.routers.llm_profiles.llm_profile_service.list_profiles"
    ).return_value = [
        LLMProfileOut(
            id=None,
            source="builtin",
            name="fake",
            provider="fake",
            model="",
            api_key_env="OPENROUTER_API_KEY",
            has_api_key=False,
            provider_config={},
            pricing=None,
            is_active=True,
            created_at=None,
        )
    ]

    response = client.get("/api/admin/llm-profiles")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "fake"
    assert data[0]["is_active"] is True


def test_create_admin_only(client, mock_service):
    response = client.post(
        "/api/admin/llm-profiles",
        json={"name": "my-openrouter", "provider": "openrouter", "model": "x"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_create_calls_service(client, override_require_admin, mock_service):
    mock_service.patch(
        "api.routers.llm_profiles.llm_profile_service.create_profile"
    ).return_value = LLMProfileOut(
        id=uuid.uuid4(),
        source="custom",
        name="my-openrouter",
        provider="openrouter",
        model="x",
        api_key_env="OPENROUTER_API_KEY",
        has_api_key=False,
        provider_config={},
        pricing=None,
        is_active=False,
        created_at=datetime.now(UTC),
    )

    response = client.post(
        "/api/admin/llm-profiles",
        json={"name": "my-openrouter", "provider": "openrouter", "model": "x"},
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["name"] == "my-openrouter"


def test_delete_calls_service(client, override_require_admin, mock_service):
    profile_id = uuid.uuid4()
    delete_mock = mock_service.patch("api.routers.llm_profiles.llm_profile_service.delete_profile")

    response = client.delete(f"/api/admin/llm-profiles/{profile_id}")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    delete_mock.assert_awaited_once()
    assert delete_mock.await_args.args[1] == profile_id


def test_activate_calls_service(client, override_require_admin, mock_service):
    response = client.post(
        "/api/admin/llm-profiles/activate", json={"source": "builtin", "name": "fake"}
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
