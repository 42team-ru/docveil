"""Проверка живости и прогрев моделей на старте."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


def test_health_returns_ok(client: TestClient) -> None:
    """`GET /api/health` отвечает без авторизации — healthcheck контейнера."""
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_warmup_runs_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """С `WARMUP_ON_START=true` модели греются до первого запроса."""
    calls: list[str] = []
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    monkeypatch.setattr("api.main.warm_up", lambda: calls.append("warm"))
    monkeypatch.setattr("api.main.settings.warmup_on_start", True)

    with TestClient(app):
        pass

    assert calls == ["warm"]


def test_warmup_skipped_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без настройки прогрева старт не тянет Natasha: дефолт — выключено."""
    calls: list[str] = []
    monkeypatch.setattr("api.main.ensure_bucket", lambda: None)
    monkeypatch.setattr("api.main.warm_up", lambda: calls.append("warm"))
    monkeypatch.setattr("api.main.settings.warmup_on_start", False)

    with TestClient(app):
        pass

    assert calls == []
