"""Настройки API-слоя из окружения (.env).

Это единая точка настройки для веб-слоя (FastAPI, БД, MinIO, JWT, порт).
Настройки самого движка обезличивания (`masker`) сюда намеренно не входят:
`masker` — отдельный слой, обязанный работать без БД/MinIO/API (CLI,
пакетный прогон по каталогу), и не должен зависеть от этого модуля. Его
провайдеры (`masker.llm.get_provider`, `masker.ocr.select.select_ocr`,
`masker.detect.gliner`) читают свои переменные окружения (``MASKER_LLM*``,
``GIGACHAT_CREDENTIALS``, ``OPENROUTER_API_KEY``, ``MASKER_OCR``,
``MASKER_GLINER_PATH`` и т.д.) напрямую из ``os.environ`` — это осознанное
решение, а не пробел: единая точка *документации* по всем переменным
проекта, включая эти, — файл ``.env.example`` в корне ``backend/``.
"""

from __future__ import annotations

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

    #: Порт, на котором uvicorn поднимает FastAPI-приложение (`make api`,
    #: `Dockerfile` CMD). Значение по умолчанию совпадает с тем, что было
    #: захардкожено раньше (`8000`), поэтому смена не меняет поведение,
    #: пока переменная `APP_PORT` не задана явно.
    app_port: int = 8000


settings = Settings()  # type: ignore[call-arg]
