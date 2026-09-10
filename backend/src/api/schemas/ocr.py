"""Схемы OCR-извлечения (POST /api/ocr/extract)."""

from __future__ import annotations

from pydantic import BaseModel


class OcrLineOut(BaseModel):
    """Одна распознанная строка с геометрией в pt страницы."""

    text: str
    #: [x0, y0, x1, y1] в pt страницы (origin — левый верхний угол страницы).
    bbox: list[float]
    #: [[x, y] × 4] в pt страницы, обход по часовой от левого верхнего.
    polygon: list[list[float]]
    confidence: float
    order: int


class OcrPageOut(BaseModel):
    """OCR-результат одной страницы."""

    page: int
    width_pt: float
    height_pt: float
    dpi: int
    lines: list[OcrLineOut]


class OcrExtractRequest(BaseModel):
    """Запрос OCR-извлечения: объект MinIO с PDF-документом."""

    object_name: str


class OcrExtractResponse(BaseModel):
    """OCR-результат всего документа: провайдер + постраничные строки."""

    provider: str
    pages: list[OcrPageOut]
