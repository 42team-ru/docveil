"""API-тест: `GET /runs/{id}/report` с PDF содержит `entities[].regions` и `pages[]`.

План feat/highlight-coords-edits, приёмка К1. Прогон гоняется на настоящей
PDF-фикстуре (``contract_pdf_01.pdf``), потому что регионы читаются из
готового ``masked_highlight.pdf``, а не из плана: одна из проверок — что
рендер действительно проставил геометрию и цепочка ``render_node →
_build_report_dict`` донесла её до отчёта.

Каркас клиента/хранилища собран так же, как в ``test_runs.py`` — не
дублируем monkeypatch MinIO, а импортируем фикстуры оттуда: сокращение,
пока набор API-тестов маленький; при росте вынесем в общий ``conftest``.
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
from api.models.llm_profile import LLMActiveSettingORM
from api.models.run import RunORM
from api.models.user import UserORM
from api.services import run_service
from masker.run import sqlite_checkpointer_factory

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_pdf_01.pdf"

_BODY = {
    "object_name": "documents/contract_pdf_01.pdf",
    "types": ["inn"],
    "rules_only": True,
    "mask_style": "marker",
}


@pytest.fixture(autouse=True)
def _no_bucket_check(monkeypatch: pytest.MonkeyPatch) -> None:
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
            await conn.run_sync(LLMActiveSettingORM.__table__.create)

    asyncio.run(_create_tables())

    async def _get_db() -> AsyncGenerator[object]:
        async with session_maker() as session:
            yield session

    async def _current_user() -> UserORM:
        return auth_user

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


def test_report_carries_regions_and_pages_for_pdf(client: TestClient, storage: Path) -> None:
    """После прогона PDF отчёт содержит ``entities[].regions`` и ``pages[]``.

    Регионы нормализованы 0..1, каждая ссылается на страницу, которая есть
    в ``pages[]``. Проверяем, что как минимум один регион и как минимум одна
    страница добрались до отчёта — а не что оба поля просто «пусто» (тогда
    новый контракт не работает).
    """
    created = _create_run(client)
    run_id = created["id"]

    report = client.get(f"/api/runs/{run_id}/report").json()

    pages = report.get("pages", [])
    assert pages, "К1: pages[] должно быть заполнено для PDF-артефакта"
    assert all("width_pt" in p and "height_pt" in p for p in pages)
    known_pages = {int(p["page"]) for p in pages}

    entities_with_regions = [
        entity for entity in report.get("entities", []) if entity.get("regions")
    ]
    assert entities_with_regions, "К1: хотя бы одна сущность должна получить regions"

    for entity in entities_with_regions:
        for region in entity["regions"]:
            assert region["page"] in known_pages
            for coord in ("x0", "y0", "x1", "y1"):
                value = region[coord]
                assert 0.0 <= value <= 1.0, (
                    f"К1: {coord}={value} у ref={entity.get('ref')} вне 0..1"
                )
            assert region["x0"] <= region["x1"]
            assert region["y0"] <= region["y1"]


def test_docx_run_has_empty_regions_and_pages(client: TestClient, storage: Path, mocker) -> None:
    """Для docx PDF-артефакта нет — ``regions: []`` и ``pages: []``, не 500."""
    docx_fixture = ROOT / "fixtures" / "labeled" / "contract_01.docx"

    def _fget(_bucket: str, _name: str, file_path: str) -> None:
        shutil.copyfile(docx_fixture, file_path)

    mocker.patch("api.services.run_service.minio_client.fget_object", side_effect=_fget)

    response = client.post(
        "/api/runs",
        json={**_BODY, "object_name": "documents/contract_01.docx"},
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    run_id = response.json()["id"]

    report = client.get(f"/api/runs/{run_id}/report").json()

    assert report.get("pages") == []
    for entity in report.get("entities", []):
        assert entity.get("regions", []) == []
