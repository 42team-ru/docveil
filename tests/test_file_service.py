"""Юнит-тесты api.services.file_service.upload_file (загрузка в MinIO)."""

from __future__ import annotations

import io

import pytest
from starlette.datastructures import Headers, UploadFile

from api.core.config import settings
from api.services.file_service import upload_file


@pytest.mark.asyncio
async def test_upload_file_calls_minio_put_object(mocker):
    mock_put_object = mocker.patch("api.services.file_service.minio_client.put_object")
    content = b"binary document content"
    file = UploadFile(
        filename="contract.pdf",
        file=io.BytesIO(content),
        headers=Headers({"content-type": "application/pdf"}),
    )

    object_name, size = await upload_file(file)

    assert size == len(content)
    assert object_name.endswith("/contract.pdf")
    mock_put_object.assert_called_once()
    args, kwargs = mock_put_object.call_args
    assert args[0] == settings.minio_bucket
    assert args[1] == object_name
    assert kwargs["length"] == len(content)
    assert kwargs["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_upload_file_defaults_content_type_when_missing(mocker):
    mock_put_object = mocker.patch("api.services.file_service.minio_client.put_object")
    file = UploadFile(filename="no_type.bin", file=io.BytesIO(b"data"))

    await upload_file(file)

    _, kwargs = mock_put_object.call_args
    assert kwargs["content_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_upload_file_object_name_is_unique_per_call(mocker):
    mocker.patch("api.services.file_service.minio_client.put_object")
    file1 = UploadFile(filename="same_name.txt", file=io.BytesIO(b"a"))
    file2 = UploadFile(filename="same_name.txt", file=io.BytesIO(b"b"))

    object_name1, _ = await upload_file(file1)
    object_name2, _ = await upload_file(file2)

    assert object_name1 != object_name2
