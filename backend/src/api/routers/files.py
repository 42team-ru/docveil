"""Роуты работы с файлами (загрузка в MinIO)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, UploadFile

from api.core.config import settings
from api.core.deps import get_current_user
from api.schemas.file import FileUploadResponse
from api.services.file_service import upload_file

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(get_current_user)])


@router.post("/upload", response_model=FileUploadResponse)
async def upload(file: UploadFile) -> FileUploadResponse:
    object_name, size = await upload_file(file)
    return FileUploadResponse(
        bucket=settings.minio_bucket,
        object_name=object_name,
        size=size,
        content_type=file.content_type,
    )
