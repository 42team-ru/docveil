"""Тесты роута POST /api/ocr/extract.

MinIO подменяется: fget_object копирует локальную фикстуру.
OCR-провайдер — FakeOCR через MASKER_OCR=fake, чтобы не тащить реальные
движки в CI. Фикстура scan_synth_01.pdf — синтетический PDF-скан из
backend/fixtures/labeled/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from api.core.deps import get_current_user
from api.main import app

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
SCAN_PDF = ROOT / "fixtures" / "labeled" / "scan_synth_01.pdf"


@pytest.fixture(autouse=True)
def _env_fake_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASKER_OCR", "fake")


@pytest.fixture(autouse=True)
def _no_bucket_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)


@pytest.fixture
def auth_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import uuid
    from datetime import UTC, datetime

    from api.models.user import UserORM

    user = UserORM(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hash",
        full_name="User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    async def _current_user() -> UserORM:
        return user

    app.dependency_overrides[get_current_user] = _current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def _mock_minio_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    """MinIO отдаёт scan_synth_01.pdf независимо от запрошенного object_name."""

    def _fget(bucket: str, object_name: str, file_path: str) -> None:
        shutil.copyfile(SCAN_PDF, file_path)

    monkeypatch.setattr("api.services.ocr_service.minio_client.fget_object", _fget)


def test_extract_requires_authorization() -> None:
    """Без авторизации — 401, как все защищённые роуты."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    with TestClient(app) as anon:
        resp = anon.post("/api/ocr/extract", json={"object_name": "documents/scan.pdf"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
    monkeypatch.undo()


def test_extract_rejects_non_pdf(auth_client: TestClient) -> None:
    """Для не-PDF объекта — 422 ещё до обращения в MinIO (суффикс отвергается сервисом)."""
    resp = auth_client.post("/api/ocr/extract", json={"object_name": "documents/contract.docx"})
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_extract_returns_pages_and_lines(auth_client: TestClient, _mock_minio_scan: None) -> None:
    """FakeOCR (пустые строки) → ответ содержит pages с полями геометрии."""
    resp = auth_client.post("/api/ocr/extract", json={"object_name": "documents/scan.pdf"})
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["provider"] == "fake"
    assert isinstance(body["pages"], list)
    assert len(body["pages"]) >= 1
    page = body["pages"][0]
    assert {"page", "width_pt", "height_pt", "dpi", "lines"} <= set(page)
    assert page["page"] == 0
    assert page["width_pt"] > 0
    assert page["height_pt"] > 0
    assert page["dpi"] == 400


def test_extract_line_fields_are_present(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если FakeOCR возвращает строку, в ответе есть все поля OcrLineOut."""
    from masker.ocr.fake import FakeOCR
    from masker.ocr.provider import OCRLine

    fake_line = OCRLine(
        text="Тест строка",
        bbox=(10.0, 20.0, 100.0, 40.0),
        polygon=((10.0, 20.0), (100.0, 20.0), (100.0, 40.0), (10.0, 40.0)),
        confidence=0.95,
        order=0,
    )

    def _fget(bucket: str, object_name: str, file_path: str) -> None:
        shutil.copyfile(SCAN_PDF, file_path)

    monkeypatch.setattr("api.services.ocr_service.minio_client.fget_object", _fget)
    monkeypatch.setattr("api.services.ocr_service.select_ocr", lambda: FakeOCR(lines=[fake_line]))

    resp = auth_client.post("/api/ocr/extract", json={"object_name": "documents/scan.pdf"})
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    # FakeOCR с одной строкой — у каждой страницы хотя бы 1 строка
    first_page_lines = body["pages"][0]["lines"]
    assert len(first_page_lines) >= 1
    line = first_page_lines[0]
    assert {"text", "bbox", "polygon", "confidence", "order"} <= set(line)
    assert line["text"] == "Тест строка"
    assert len(line["bbox"]) == 4
    assert len(line["polygon"]) == 4
    assert abs(line["confidence"] - 0.95) < 1e-6
