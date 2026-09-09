"""Тесты `Settings`: единая точка настройки API-слоя.

`settings` — синглтон, создаваемый один раз при импорте модуля, поэтому
проверка дефолтов и переопределений строится на отдельных экземплярах
`Settings`, а не на самом синглтоне (иначе тесты подглядывали бы за
окружением, выставленным `conftest.py`, и порядком импорта).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api.core.config import Settings, _yaml_settings_source

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


def test_yaml_port_is_used_until_environment_overrides_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "masker.yaml"
    path.write_text("application:\n  port: 8100\n", encoding="utf-8")
    monkeypatch.setenv("MASKER_CONFIG", str(path))
    monkeypatch.delenv("APP_PORT", raising=False)
    _set_required_env(monkeypatch)

    assert Settings(_env_file=None).app_port == 8100

    monkeypatch.setenv("APP_PORT", "9100")
    assert Settings(_env_file=None).app_port == 9100


def test_yaml_web_settings_resolve_named_secrets_without_storing_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "masker.yaml"
    path.write_text(
        """application:
  port: 8100
web:
  database:
    host: db.example.test
    port: 5433
    name: documents
    user: api
    password_env: TEST_DATABASE_PASSWORD
  minio:
    endpoint: minio.example.test:9000
    access_key_env: TEST_MINIO_ACCESS_KEY
    secret_key_env: TEST_MINIO_SECRET_KEY
  jwt:
    secret_env: TEST_JWT_SECRET
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MASKER_CONFIG", str(path))
    monkeypatch.setenv("TEST_DATABASE_PASSWORD", "database-password")
    monkeypatch.setenv("TEST_MINIO_ACCESS_KEY", "access-key")
    monkeypatch.setenv("TEST_MINIO_SECRET_KEY", "secret-key")
    monkeypatch.setenv("TEST_JWT_SECRET", "jwt-secret")

    values = _yaml_settings_source()

    assert values["app_port"] == 8100
    assert (
        values["database_url"]
        == "postgresql+asyncpg://api:database-password@db.example.test:5433/documents"
    )
    assert values["minio_access_key"] == "access-key"
    assert values["minio_secret_key"] == "secret-key"
    assert values["jwt_secret"] == "jwt-secret"
