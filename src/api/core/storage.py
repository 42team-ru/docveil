"""Настройка клиента MinIO (S3-совместимое хранилище файлов)."""

from __future__ import annotations

from minio import Minio

from api.core.config import settings

minio_client = Minio(
    settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)


def ensure_bucket() -> None:
    """Создать бакет, если его ещё нет (идемпотентно). Вызывается при старте приложения."""
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)
