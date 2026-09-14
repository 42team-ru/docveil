"""Загрузка файлов в MinIO."""

from __future__ import annotations

import io
import uuid

from fastapi import HTTPException, UploadFile
from minio.error import S3Error
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.storage import minio_client


async def upload_file(file: UploadFile) -> tuple[str, int]:
    """Загрузить файл в MinIO. Возвращает (object_name, размер в байтах)."""
    content = await file.read()
    object_name = f"{uuid.uuid4()}/{file.filename}"

    def _put() -> None:
        minio_client.put_object(
            settings.minio_bucket,
            object_name,
            io.BytesIO(content),
            length=len(content),
            content_type=file.content_type or "application/octet-stream",
        )

    try:
        await run_in_threadpool(_put)
    except S3Error as exc:
        if exc.code == "XMinioStorageFull":
            raise HTTPException(
                status_code=507,
                detail="Хранилище заполнено. Освободите место и повторите попытку.",
            ) from exc
        raise HTTPException(status_code=503, detail=f"Ошибка хранилища: {exc.code}") from exc
    return object_name, len(content)


def download_file(object_name: str) -> bytes:
    """Скачать произвольный объект из MinIO (аватары и т.п.)."""
    response = minio_client.get_object(settings.minio_bucket, object_name)
    try:
        return bytes(response.read())
    finally:
        response.close()
        response.release_conn()
