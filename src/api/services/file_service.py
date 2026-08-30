"""Загрузка файлов в MinIO."""

from __future__ import annotations

import io
import uuid

from fastapi import UploadFile
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

    await run_in_threadpool(_put)
    return object_name, len(content)
