"""Тесты роутов прогона маскирования — веб как второй вызывающий графа.

Реальные MinIO и Postgres не нужны: объект хранилища подменяется копированием
локальной фикстуры, метаданные прогонов лежат в sqlite на `tmp_path`, а
чекпойнтер графа переопределён на файл там же. Опции прогона — `rules_only`
по одному типу: детекция правилами без NER и LLM, граф встаёт на вопросы
политики за доли секунды (тот же приём, что в `tests/masker/test_run.py`).
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncGenerator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.core.db import get_db
from api.core.deps import get_current_user
from api.main import app
from api.models.run import RunORM
from api.models.user import UserORM
from api.services import run_service
from masker.run import sqlite_checkpointer_factory

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"

_BODY = {
    "object_name": "documents/contract_01.docx",
    "types": ["inn"],
    "rules_only": True,
    "mask_style": "marker",
}


@pytest.fixture(autouse=True)
def _no_bucket_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Старт приложения не должен идти в живой MinIO за бакетом."""
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)


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
def storage(tmp_path: Path, mocker) -> Path:
    """MinIO на файловой системе: скачивание — копия фикстуры, выгрузка — в каталог."""
    objects = tmp_path / "minio"
    objects.mkdir()

    def _fget_object(bucket: str, object_name: str, file_path: str) -> None:
        shutil.copyfile(FIXTURE, file_path)

    def _fput_object(bucket: str, object_name: str, file_path: str) -> None:
        target = objects / object_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file_path, target)

    mocker.patch("api.services.run_service.minio_client.fget_object", side_effect=_fget_object)
    mocker.patch("api.services.run_service.minio_client.fput_object", side_effect=_fput_object)
    mocker.patch(
        "api.services.run_service.artifact_bytes",
        side_effect=lambda run_id, name: (objects / f"runs/{run_id}/{name}").read_bytes(),
    )
    return objects


@pytest.fixture
def client(
    tmp_path: Path, auth_user: UserORM, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'runs.sqlite').as_posix()}", poolclass=NullPool
    )
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_tables() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(RunORM.__table__.create)

    asyncio.run(_create_tables())

    async def _get_db() -> AsyncGenerator[object]:
        async with session_maker() as session:
            yield session

    async def _current_user() -> UserORM:
        return auth_user

    # Фоновая задача живёт дольше запроса и берёт свою сессию — ей нужен тот же
    # движок, что и запросу, иначе она запишет статус в чужую базу.
    monkeypatch.setattr("api.services.run_service.async_session_maker", session_maker)

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[run_service.get_run_checkpointer_factory] = lambda: (
        sqlite_checkpointer_factory(tmp_path / "graph-state.sqlite")
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _create_run(client: TestClient) -> dict[str, object]:
    response = client.post("/api/runs", json=_BODY)
    assert response.status_code == status.HTTP_202_ACCEPTED
    return dict(response.json())


def test_create_run_requires_authorization() -> None:
    """Без переопределённого пользователя роут закрыт — как `files`/`custom_types`."""
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/runs", json=_BODY).status_code == (status.HTTP_401_UNAUTHORIZED)


def test_create_run_rejects_unsupported_format(client: TestClient) -> None:
    response = client.post("/api/runs", json={**_BODY, "object_name": "documents/report.txt"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_run_pauses_on_questions_and_exposes_envelope(client: TestClient, storage: Path) -> None:
    """Прогон доходит до `ask_human`, и конверт вопросов виден по HTTP как есть."""
    created = _create_run(client)
    assert created["status"] == "queued"

    state = client.get(f"/api/runs/{created['id']}").json()
    assert state["status"] == "awaiting_answers"
    assert state["document"] == {"name": "contract_01.docx", "format": "docx"}

    questions = client.get(f"/api/runs/{created['id']}/questions").json()
    assert questions["schema_version"] == 1
    assert questions["questions"]
    assert {"id", "kind", "target", "options", "default"} <= set(questions["questions"][0])


def test_report_and_artifacts_appear_only_after_answers(client: TestClient, storage: Path) -> None:
    """Пока граф стоит на вопросах, узлы `render`/`report` не выполнялись."""
    created = _create_run(client)
    run_id = created["id"]

    assert client.get(f"/api/runs/{run_id}/report").status_code == status.HTTP_404_NOT_FOUND
    assert client.get(f"/api/runs/{run_id}/artifacts").json() == []

    answers = client.post(f"/api/runs/{run_id}/answers", json={"answers": {}})
    assert answers.status_code == status.HTTP_202_ACCEPTED

    # После ответов граф доходит до отчёта и встаёт на втором прерывании —
    # ждёт правок оператора. Отчёт и артефакты на этот момент уже есть.
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "awaiting_review"

    report = client.get(f"/api/runs/{run_id}/report").json()
    assert report["report_version"] == 4
    assert report["input"] == "contract_01.docx"

    artifacts = client.get(f"/api/runs/{run_id}/artifacts").json()
    roles = {artifact["role"] for artifact in artifacts}
    assert {"preview", "masked_highlight"} <= roles
    assert all(
        artifact["url"].startswith(f"/api/runs/{run_id}/artifacts/") for artifact in artifacts
    )


def test_review_edits_finish_the_run(client: TestClient, storage: Path) -> None:
    """Утверждение документа применяет правки вторым кругом графа и завершает прогон."""
    created = _create_run(client)
    run_id = created["id"]
    client.post(f"/api/runs/{run_id}/answers", json={"answers": {}})

    payload = client.get(f"/api/runs/{run_id}/review").json()
    assert payload["schema_version"] == 1
    assert payload["report"]["report_version"] == 4

    applied = client.post(
        f"/api/runs/{run_id}/review",
        json={"edits": {"decisions": {}, "type_overrides": {}, "manual": []}},
    )

    assert applied.status_code == status.HTTP_202_ACCEPTED
    finished = client.get(f"/api/runs/{run_id}").json()
    assert finished["status"] in {"done", "leaked"}
    assert finished["finished_at"] is not None


def test_review_edits_before_report_are_rejected(client: TestClient, storage: Path) -> None:
    """Пока прогон стоит на вопросах, правок он не ждёт — 409, а не молча в граф."""
    created = _create_run(client)

    response = client.post(f"/api/runs/{created['id']}/review", json={"edits": {}})

    assert response.status_code == status.HTTP_409_CONFLICT


def test_questions_endpoint_does_not_serve_review_payload(
    client: TestClient, storage: Path
) -> None:
    """Два прерывания — два конверта: на паузе правок вопросов нет."""
    created = _create_run(client)
    client.post(f"/api/runs/{created['id']}/answers", json={"answers": {}})

    response = client.get(f"/api/runs/{created['id']}/questions")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_artifact_download_returns_docx_bytes(client: TestClient, storage: Path) -> None:
    created = _create_run(client)
    run_id = created["id"]
    client.post(f"/api/runs/{run_id}/answers", json={"answers": {}})

    response = client.get(f"/api/runs/{run_id}/artifacts/masked_highlight")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    # DOCX — это ZIP: подпись файла проверяется байтами, а не заголовком ответа.
    assert response.content[:2] == b"PK"


def test_unknown_artifact_role_is_404(client: TestClient, storage: Path) -> None:
    created = _create_run(client)
    client.post(f"/api/runs/{created['id']}/answers", json={"answers": {}})

    response = client.get(f"/api/runs/{created['id']}/artifacts/masked_gold")

    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_answers_on_finished_run_are_rejected(client: TestClient, storage: Path) -> None:
    """Повторные ответы прогону, который их уже не ждёт, — 409, а не новый прогон молча."""
    created = _create_run(client)
    run_id = created["id"]
    client.post(f"/api/runs/{run_id}/answers", json={"answers": {}})

    repeated = client.post(f"/api/runs/{run_id}/answers", json={"answers": {}})

    assert repeated.status_code == status.HTTP_409_CONFLICT


def test_answers_with_wrong_schema_version_are_422(client: TestClient, storage: Path) -> None:
    created = _create_run(client)

    response = client.post(
        f"/api/runs/{created['id']}/answers", json={"schema_version": 2, "answers": {}}
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_image_output_format_default_is_accepted(client: TestClient, storage: Path) -> None:
    """image_output_format=«original» (дефолт) принимается без ошибок."""
    response = client.post("/api/runs", json={**_BODY, "image_output_format": "original"})
    assert response.status_code == status.HTTP_202_ACCEPTED


def test_image_output_format_pdf_is_accepted(client: TestClient, storage: Path) -> None:
    """image_output_format=«pdf» также принимается (конвертация картинки)."""
    response = client.post("/api/runs", json={**_BODY, "image_output_format": "pdf"})
    assert response.status_code == status.HTTP_202_ACCEPTED


def test_unknown_run_id_is_404(client: TestClient) -> None:
    assert client.get(f"/api/runs/{uuid.uuid4()}").status_code == status.HTTP_404_NOT_FOUND


def test_foreign_run_is_not_visible(client: TestClient, storage: Path) -> None:
    """Прогон чужого пользователя недоступен так же, как несуществующий."""
    created = _create_run(client)

    app.dependency_overrides[get_current_user] = lambda: UserORM(
        id=uuid.uuid4(),
        email="other@example.com",
        password_hash="hash",
        full_name="Other",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    assert client.get(f"/api/runs/{created['id']}").status_code == status.HTTP_404_NOT_FOUND


def test_history_lists_runs_of_current_user(client: TestClient, storage: Path) -> None:
    _create_run(client)
    _create_run(client)

    listing = client.get("/api/runs").json()

    assert listing["total"] == 2
    assert len(listing["items"]) == 2
    assert listing["items"][0]["document"]["name"] == "contract_01.docx"
    assert client.get("/api/runs", params={"query": "нет-такого"}).json()["total"] == 0
