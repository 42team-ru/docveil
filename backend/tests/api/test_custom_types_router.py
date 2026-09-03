"""Тесты роутов компиляции пользовательских типов (T1.13, шаг 8 — заглушка).

Логики компилятора здесь ещё нет (шаг 9) — эти тесты проверяют маршруты,
авторизацию и форму ответа, не содержимое `compiled`/`failed`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import status

from api.core.deps import get_current_user
from api.main import app
from api.models.user import UserORM


@pytest.fixture
def auth_user() -> UserORM:
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
def override_get_current_user(auth_user: UserORM):
    async def _mock_get_current_user() -> UserORM:
        return auth_user

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)


_VALID_BODY = {
    "object_name": "documents/contract.docx",
    "descriptions": ["замажь даты отгрузки", "замажь коды товаров"],
}


def test_compile_requires_authorization(client) -> None:
    response = client.post("/api/custom_types/compile", json=_VALID_BODY)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_compile_valid_body_returns_compile_response_shape(
    client, override_get_current_user
) -> None:
    response = client.post("/api/custom_types/compile", json=_VALID_BODY)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["thread_id"]
    assert data["status"] in {"done", "waiting"}
    assert data["compiled"] == []
    assert len(data["failed"]) == len(_VALID_BODY["descriptions"])
    assert data["failed"][0]["index"] == 0
    assert data["failed"][0]["description"] == _VALID_BODY["descriptions"][0]
    assert data["questions"] == []


def test_compile_rejects_empty_descriptions(client, override_get_current_user) -> None:
    response = client.post(
        "/api/custom_types/compile",
        json={"object_name": "documents/contract.docx", "descriptions": []},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_compile_two_calls_return_different_thread_ids(client, override_get_current_user) -> None:
    first = client.post("/api/custom_types/compile", json=_VALID_BODY).json()
    second = client.post("/api/custom_types/compile", json=_VALID_BODY).json()
    assert first["thread_id"] != second["thread_id"]


def test_answers_requires_authorization(client) -> None:
    response = client.post("/api/custom_types/compile/unknown-thread/answers", json={"answers": {}})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_answers_unknown_thread_id_is_404(client, override_get_current_user) -> None:
    response = client.post(
        "/api/custom_types/compile/unknown-thread/answers", json={"answers": {"Q1": "mask"}}
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_answers_to_thread_from_compile_is_still_404(client, override_get_current_user) -> None:
    """Заглушка никогда не встаёт на паузу — даже свежий `thread_id` из `/compile`
    не годится для `/answers`, потому что ждать ответа ему нечего (шаг 8)."""
    compiled = client.post("/api/custom_types/compile", json=_VALID_BODY).json()

    response = client.post(
        f"/api/custom_types/compile/{compiled['thread_id']}/answers",
        json={"answers": {"Q1": "mask"}},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
