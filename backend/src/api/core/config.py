"""Настройки приложения из окружения (.env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()  # type: ignore[call-arg]
