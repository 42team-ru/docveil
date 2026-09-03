"""Тесты роутов компиляции пользовательских типов (T1.13, шаг 12 — связка с графом).

Документ скачивается роутом из MinIO — в тестах `minio_client.fget_object`
подменяется на копирование локальной фикстуры, реальный MinIO не нужен.
Чекпойнтер сессий компиляции переопределён на `tmp_path`, чтобы тесты не
писали `data/custom_types_compile.sqlite` рядом с исходниками.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import status

from api.core.deps import get_current_user
from api.main import app
from api.models.user import UserORM
from api.services import custom_types_service
from masker.llm import FakeProvider
from masker.run import sqlite_checkpointer_factory

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


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


@pytest.fixture
def override_checkpointer(tmp_path: Path):
    """Компиляция пишет чекпойнты в SQLite на `tmp_path`, не в `data/` репозитория."""
    factory = sqlite_checkpointer_factory(tmp_path / "compile_state.sqlite")

    app.dependency_overrides[custom_types_service.get_compile_checkpointer_factory] = lambda: (
        factory
    )
    yield
    app.dependency_overrides.pop(custom_types_service.get_compile_checkpointer_factory, None)


@pytest.fixture
def mock_minio_download(mocker):
    """`fget_object` копирует локальную фикстуру вместо обращения к MinIO."""

    def _fget_object(bucket: str, object_name: str, file_path: str) -> None:
        shutil.copyfile(FIXTURE, file_path)

    return mocker.patch(
        "api.services.custom_types_service.minio_client.fget_object", side_effect=_fget_object
    )


def _override_llm(responses: list[str]):
    provider = FakeProvider(responses)
    app.dependency_overrides[custom_types_service.get_llm_provider] = lambda: provider
    return provider


@pytest.fixture
def clear_llm_override():
    yield
    app.dependency_overrides.pop(custom_types_service.get_llm_provider, None)


_VALID_BODY = {
    "object_name": "documents/contract.docx",
    "descriptions": ["замажь даты отгрузки", "замажь коды товаров"],
}


def test_compile_requires_authorization(client) -> None:
    response = client.post("/api/custom_types/compile", json=_VALID_BODY)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_compile_valid_body_returns_compile_response_shape(
    client, override_get_current_user, override_checkpointer, mock_minio_download
) -> None:
    """Без сценарных ответов провайдера (`fake`, пустая очередь) LLM возвращает
    ответ не в формате компилятора — оба описания честно проваливаются."""
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
    assert set(data["engine_capabilities"]) >= {"literals", "regex", "regex_context"}


def test_compile_rejects_empty_descriptions(client, override_get_current_user) -> None:
    response = client.post(
        "/api/custom_types/compile",
        json={"object_name": "documents/contract.docx", "descriptions": []},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_compile_two_calls_return_different_thread_ids(
    client, override_get_current_user, override_checkpointer, mock_minio_download
) -> None:
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


def test_answers_to_thread_from_compile_is_still_404(
    client, override_get_current_user, override_checkpointer, mock_minio_download
) -> None:
    """Оба описания без сценарного ответа сразу проваливаются в `cannot_compile` —
    граф не встаёт на паузу, `thread_id` из `/compile` не годится для `/answers`."""
    compiled = client.post("/api/custom_types/compile", json=_VALID_BODY).json()
    assert compiled["status"] == "done"

    response = client.post(
        f"/api/custom_types/compile/{compiled['thread_id']}/answers",
        json={"answers": {"Q1": "mask"}},
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_compile_end_to_end_with_fake_provider_returns_real_preview(
    client,
    override_get_current_user,
    override_checkpointer,
    mock_minio_download,
    clear_llm_override,
) -> None:
    """Сквозной тест шага 12: загрузка фикстуры → compile с описанием → 200
    с непустым `compiled[0].preview.total_matches`."""
    spec = {
        "id": "internal_ref",
        "title": "Внутренний номер",
        "marker": "[НОМЕР-{n}]",
        "critical": False,
        "detect": {"kind": "literals", "values": ["3662103003"]},
    }
    _override_llm([json.dumps({"outcome": "compile", "spec": spec})])

    response = client.post(
        "/api/custom_types/compile",
        json={
            "object_name": "documents/contract.docx",
            "descriptions": ["замажь номер 3662103003"],
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "done"
    assert len(data["compiled"]) == 1
    assert data["compiled"][0]["outcome"] == "compile"
    assert data["compiled"][0]["spec"]["id"] == "internal_ref"
    assert data["compiled"][0]["preview"]["total_matches"] == 1
    assert data["failed"] == []


def test_compile_use_builtin_outcome_has_no_spec_but_has_type_id(
    client,
    override_get_current_user,
    override_checkpointer,
    mock_minio_download,
    clear_llm_override,
) -> None:
    _override_llm(
        [json.dumps({"outcome": "use_builtin", "type_id": "person", "marker_override": None})]
    )

    response = client.post(
        "/api/custom_types/compile",
        json={"object_name": "documents/contract.docx", "descriptions": ["замажь ФИО"]},
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["compiled"][0]["outcome"] == "use_builtin"
    assert data["compiled"][0]["type_id"] == "person"
    assert data["compiled"][0]["spec"] is None
    assert data["compiled"][0]["preview"] is None


def test_compile_ask_outcome_pauses_and_answers_resumes(
    client,
    override_get_current_user,
    override_checkpointer,
    mock_minio_download,
    clear_llm_override,
) -> None:
    spec = {
        "id": "shipment_date",
        "title": "Дата отгрузки",
        "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
        "critical": False,
        "detect": {"kind": "regex", "pattern": r"\d{2}\.\d{2}\.\d{4}"},
    }
    _override_llm(
        [
            json.dumps(
                {
                    "outcome": "ask",
                    "question": "Какую дату?",
                    "options": ["отгрузки"],
                    "target": "T1",
                }
            ),
            json.dumps({"outcome": "compile", "spec": spec}),
        ]
    )

    first = client.post(
        "/api/custom_types/compile",
        json={"object_name": "documents/contract.docx", "descriptions": ["замажь дату"]},
    ).json()

    assert first["status"] == "waiting"
    assert len(first["questions"]) == 1
    question_id = first["questions"][0]["id"]

    second = client.post(
        f"/api/custom_types/compile/{first['thread_id']}/answers",
        json={"answers": {question_id: "отгрузки"}},
    )

    assert second.status_code == status.HTTP_200_OK
    data = second.json()
    assert data["status"] == "done"
    assert data["compiled"][0]["spec"]["id"] == "shipment_date"
