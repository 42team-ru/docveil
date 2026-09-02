import io
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from api.core.deps import get_current_user
from api.main import app
from api.models.user import UserORM


@pytest.fixture
def auth_user():
    return UserORM(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hash",
        full_name="User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def override_get_current_user(auth_user):
    async def _mock_get_current_user():
        return auth_user

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_file_service(mocker):
    return mocker.patch("api.routers.files.upload_file", new_callable=AsyncMock)


def test_upload_file_success(client, override_get_current_user, mock_file_service):
    # Mock upload_file to return object_name and size
    mock_file_service.return_value = ("documents/test_file.pdf", 1024)

    file_content = b"fake pdf content"
    response = client.post(
        "/api/files/upload",
        files={"file": ("test_file.pdf", io.BytesIO(file_content), "application/pdf")},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["object_name"] == "documents/test_file.pdf"
    assert data["size"] == 1024
    assert data["content_type"] == "application/pdf"
    assert "bucket" in data


def test_upload_file_unauthorized_without_token(client, mock_file_service):
    file_content = b"fake pdf content"
    response = client.post(
        "/api/files/upload",
        files={"file": ("test_file.pdf", io.BytesIO(file_content), "application/pdf")},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    mock_file_service.assert_not_called()


def test_upload_file_missing_file_field(client, override_get_current_user):
    response = client.post("/api/files/upload")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
