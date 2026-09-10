"""Роут OCR-извлечения — POST /api/ocr/extract."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from api.core.deps import get_current_user
from api.schemas.ocr import OcrExtractRequest, OcrExtractResponse
from api.services import ocr_service

router = APIRouter(prefix="/ocr", tags=["ocr"], dependencies=[Depends(get_current_user)])


@router.post("/extract", response_model=OcrExtractResponse)
async def extract_ocr(request: OcrExtractRequest) -> OcrExtractResponse:
    """Распознать все страницы PDF и вернуть постраничные строки с геометрией."""
    try:
        return await run_in_threadpool(ocr_service.extract_ocr, request)
    except ocr_service.UnsupportedFormatError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
