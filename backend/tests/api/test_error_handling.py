"""Необработанное исключение в роуте: 500 без утечки деталей, лог с трейсбеком.

Раньше такое исключение уходило только в дефолтный traceback uvicorn без
контекста запроса — причину 500 нельзя было восстановить по логам (см.
AGENTS.md, «очень слабое логирование»). Регрессия ловит оба симптома сразу:
ответ клиенту остаётся общим, а серверный лог — содержательным.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from api.core.db import get_db
from api.core.deps import get_current_user
from api.main import app
from api.models.user import UserORM


def _fake_user() -> UserORM:
    return UserORM(
        id=uuid.uuid4(),
        email="err@example.com",
        password_hash="hash",
        full_name="Err User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )


async def _broken_get_db():
    raise RuntimeError("db is on fire")
    yield  # pragma: no cover - нужен только чтобы функция осталась генератором


def test_unhandled_exception_returns_generic_500_and_is_logged(monkeypatch, caplog) -> None:
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    app.dependency_overrides[get_db] = _broken_get_db
    app.dependency_overrides[get_current_user] = _fake_user

    try:
        with (
            caplog.at_level(logging.ERROR),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            response = client.get("/api/runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json() == {"detail": "Внутренняя ошибка сервера"}
    # Тело ответа не выдаёт причину — она должна быть в логе, а не у клиента.
    assert "db is on fire" not in response.text

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "необработанное исключение должно попасть в лог"
    assert any(r.exc_info is not None for r in error_records), "лог должен нести трейсбек"
    # Причина исключения — в трейсбеке (exc_info), а не в тексте самого сообщения.
    assert "db is on fire" in caplog.text
    assert any(getattr(r, "request_id", "-") != "-" for r in error_records)


def test_request_id_header_is_present_on_success(monkeypatch) -> None:
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers.get("x-request-id")
