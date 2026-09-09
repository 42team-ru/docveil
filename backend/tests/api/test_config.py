"""Тесты `Settings`: единая точка настройки API-слоя.

`settings` — синглтон, создаваемый один раз при импорте модуля, поэтому
проверка дефолтов и переопределений строится на отдельных экземплярах
`Settings`, а не на самом синглтоне (иначе тесты подглядывали бы за
окружением, выставленным `conftest.py`, и порядком импорта).
"""

from __future__ import annotations

import pytest

from api.core.config import Settings

_REQUIRED_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "JWT_SECRET": "test-jwt-secret-key-32-bytes!!!!",
    "MINIO_ENDPOINT": "localhost:9000",
    "MINIO_ACCESS_KEY": "test-access-key",
    "MINIO_SECRET_KEY": "test-secret-key",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_app_port_defaults_to_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("APP_PORT", raising=False)

    config = Settings()

    assert config.app_port == 8000


def test_app_port_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("APP_PORT", "9100")

    config = Settings()

    assert config.app_port == 9100
