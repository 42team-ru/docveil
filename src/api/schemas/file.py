"""Схемы для работы с файлами в MinIO."""

from __future__ import annotations

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    bucket: str
    object_name: str
    size: int
    content_type: str | None = None
