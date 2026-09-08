"""Настройки веб-слоя: окружение → YAML → дефолты в коде.

``masker`` не импортирует этот модуль: CLI и движок по-прежнему запускаются
без API, БД и MinIO. Общий YAML разбирается его лёгким модулем конфигурации,
который не имеет зависимостей от веб-слоя.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import quote

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from masker.config import project_section


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    cookie_secure: bool = True

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool = False
    minio_bucket: str = "documents"

    #: Порт, на котором uvicorn поднимает FastAPI-приложение (`make api`,
    #: `Dockerfile` CMD). Значение по умолчанию совпадает с тем, что было
    #: захардкожено раньше (`8000`), поэтому смена не меняет поведение,
    #: пока переменная `APP_PORT` не задана явно.
    app_port: int = 8000
    #: Чекпойнтер графа маскирования. `postgres` — рабочий режим веб-сервера
    #: (`SqliteSaver` однопоточный, см. `masker.run`); `sqlite` оставлен для
    #: локального запуска без поднятой базы. Выбор явный: молчаливого отката
    #: на sqlite при недоступном Postgres здесь нет.
    run_checkpointer: Literal["postgres", "sqlite"] = "postgres"
    run_state_db: Path = Path("data/runs.sqlite")

    #: Источники, которым браузер разрешит ходить в API. Список явный, а не
    #: `*`: запросы идут с `credentials` (refresh-токен в cookie), а с
    #: подстановочным источником браузер такие запросы блокирует. По
    #: умолчанию — дев-сервер Vite (`yarn dev`, порт 5173) на обоих написаниях
    #: локального хоста: `localhost` и `127.0.0.1` — разные Origin.
    #: Прод-домен добавляется через `CORS_ORIGINS` в окружении, списком через
    #: запятую.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` как список; пустые элементы отбрасываются."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Внешнее окружение и .env имеют приоритет над общим YAML-файлом."""
        del cls, settings_cls
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            cast(PydanticBaseSettingsSource, _yaml_settings_source),
            file_secret_settings,
        )


def _yaml_settings_source() -> dict[str, Any]:
    """Преобразовать несекретную секцию ``web`` YAML в прежние поля Settings."""
    web = project_section("web")
    result: dict[str, Any] = {}

    application = project_section("application")
    if "port" in application:
        result["app_port"] = application["port"]

    database = _mapping(web, "database")
    password = _secret_by_name(database, "password_env")
    if password is not None:
        host = _text(database, "host")
        name = _text(database, "name")
        user = _text(database, "user")
        port = database.get("port")
        if host is not None and name is not None and user is not None and isinstance(port, int):
            result["database_url"] = (
                f"postgresql+asyncpg://{quote(user, safe='')}:{quote(password, safe='')}@"
                f"{host}:{port}/{name}"
            )

    minio = _mapping(web, "minio")
    endpoint = _text(minio, "endpoint")
    access_key = _secret_by_name(minio, "access_key_env")
    secret_key = _secret_by_name(minio, "secret_key_env")
    if endpoint is not None and access_key is not None and secret_key is not None:
        result.update(
            minio_endpoint=endpoint,
            minio_access_key=access_key,
            minio_secret_key=secret_key,
        )
    _copy_if_present(result, minio, "secure", "minio_secure")
    _copy_if_present(result, minio, "bucket", "minio_bucket")

    jwt = _mapping(web, "jwt")
    jwt_secret = _secret_by_name(jwt, "secret_env")
    if jwt_secret is not None:
        result["jwt_secret"] = jwt_secret
    _copy_if_present(result, jwt, "algorithm", "jwt_algorithm")
    _copy_if_present(result, jwt, "access_token_expire_minutes", "access_token_expire_minutes")
    _copy_if_present(result, jwt, "refresh_token_expire_days", "refresh_token_expire_days")
    _copy_if_present(result, jwt, "cookie_secure", "cookie_secure")
    return result


def _mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"web.{key} в YAML-конфиге должен быть объектом")
    return value


def _text(parent: Mapping[str, Any], key: str) -> str | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"поле {key} в YAML-конфиге должно быть строкой")
    return value


def _secret_by_name(parent: Mapping[str, Any], key: str) -> str | None:
    env_name = _text(parent, key)
    if not env_name:
        return None
    return os.environ.get(env_name) or _dotenv_values().get(env_name)


def _dotenv_values() -> Mapping[str, str | None]:
    """Взять именованные секреты и из `.env`, не заставляя masker читать его."""
    path = Path.cwd() / ".env"
    return dotenv_values(path) if path.is_file() else {}


def _copy_if_present(
    target: dict[str, Any], source: Mapping[str, Any], source_key: str, target_key: str
) -> None:
    if source_key in source:
        target[target_key] = source[source_key]


settings = Settings()  # type: ignore[call-arg]
