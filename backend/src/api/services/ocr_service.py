"""OCR-слой веб-API: распознавание PDF-страниц через masker.ingest.scan_ingest.

Маршрут: POST /api/ocr/extract — скачать документ из MinIO, прогнать через
выбранный OCR-провайдер и вернуть постраничные строки с координатами в pt.
Координаты конвертируются из пикселей провайдера с учётом ``_OCR_DPI``;
за выбор провайдера отвечает ``masker.ocr.select.select_ocr`` (``MASKER_OCR``
→ YAML → ``tesseract``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from api.core.config import settings
from api.core.storage import minio_client
from api.schemas.ocr import OcrExtractRequest, OcrExtractResponse, OcrLineOut, OcrPageOut
from masker.ingest.scan_ingest import OcrPageResult, _OCR_DPI, ocr_pages_from_pdf
from masker.ocr.select import ENV_VAR, select_ocr

__all__ = [
    "UnsupportedFormatError",
    "extract_ocr",
]

#: Форматы, которые OCR-эндпоинт принимает (PDF → страницы → pixmap → OCR).
SUPPORTED_SUFFIXES = frozenset({".pdf"})


class UnsupportedFormatError(Exception):
    """Формат документа не поддерживается OCR-извлечением."""


def _resolved_provider_name() -> str:
    """Имя OCR-провайдера по приоритету: MASKER_OCR → tesseract."""
    return os.environ.get(ENV_VAR, "tesseract")


def _download_to_tempfile(object_name: str) -> Path:
    handle, raw = tempfile.mkstemp(suffix=".pdf")
    os.close(handle)
    tmp = Path(raw)
    minio_client.fget_object(settings.minio_bucket, object_name, str(tmp))
    return tmp


def _pt_per_px(dpi: int) -> float:
    return 72.0 / dpi


def _page_result_to_out(result: OcrPageResult, dpi: int) -> OcrPageOut:
    scale = _pt_per_px(dpi)
    lines: list[OcrLineOut] = []
    for i, line in enumerate(result.lines):
        x0, y0, x1, y1 = line.bbox
        polygon_pt = [[p[0] * scale, p[1] * scale] for p in line.polygon]
        lines.append(
            OcrLineOut(
                text=line.text,
                bbox=[x0 * scale, y0 * scale, x1 * scale, y1 * scale],
                polygon=polygon_pt,
                confidence=line.confidence,
                order=i,
            )
        )
    return OcrPageOut(
        page=result.page,
        width_pt=result.width_pt,
        height_pt=result.height_pt,
        dpi=dpi,
        lines=lines,
    )


def extract_ocr(request: OcrExtractRequest) -> OcrExtractResponse:
    """Распознать все страницы PDF и вернуть строки с bbox/polygon в pt."""
    suffix = Path(request.object_name).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(
            f"OCR-извлечение поддерживает только PDF; получен суффикс {suffix!r}"
        )
    tmp = _download_to_tempfile(request.object_name)
    try:
        ocr = select_ocr()
        dpi = _OCR_DPI
        results = ocr_pages_from_pdf(tmp, ocr, dpi=dpi)
        pages = [_page_result_to_out(r, dpi) for r in results]
        return OcrExtractResponse(provider=_resolved_provider_name(), pages=pages)
    finally:
        tmp.unlink(missing_ok=True)
