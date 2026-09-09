"""Вспомогательные функции скан-ingest'а.

Отвечает за два вопроса, которые ``pdf_ingest.py`` не может ответить сам:

1. **Роутинг**: является ли страница сканом (``_page_is_scan``)?
   Страница — скан если:
   a. Текстовый слой пуст ``page.get_text("text") == ""``; или
   b. Текст есть, но покрывает < :data:`_TEXT_COVERAGE_THRESHOLD` площади
      страницы **и** на странице есть растровые изображения — «двухслойная
      ловушка»: сканер вписал невидимый OCR-слой поверх картинки.

2. **OCR-сегменты**: для каждой скан-страницы вызвать провайдер, пересчитать
   пиксельные координаты в pt страницы и завернуть строки в ``Segment``-ы
   с ``origin="ocr"`` (``ocr_segments_for_page``).

Модуль не импортирует ``masker.ocr.paddle`` или другие движки напрямую —
только контракт ``OCRProvider``, чтобы не нарушить тест изоляции слоя
``test_layer_boundary.py``.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pymupdf

from masker.model import Anchor, Segment
from masker.ocr.provider import OCRProvider

#: Если площадь символьных боксов к площади страницы меньше порога,
#: страница считается «двухслойной ловушкой» (скан + невидимый OCR-слой).
#: 0.05 — 5% площади. Калибруется на синтетическом корпусе в O5;
#: для явно пустых страниц (чистый скан) роутер возвращает True раньше,
#: не доходя до этого порога.
_TEXT_COVERAGE_THRESHOLD: float = 0.05

#: DPI рендера страницы в растр для передачи в OCR-движок.
#: 300 dpi — стандарт для офисных документов; при меньшем разрешении
#: PaddleOCR теряет мелкие глифы, при большем — растёт память.
_OCR_DPI: int = 300


def _page_is_scan(page: pymupdf.Page) -> bool:
    """Вернуть ``True``, если страница должна обрабатываться через OCR.

    Два случая:
    * Текстовый слой пуст — типичный скан без наложенного текста.
    * Текст есть, но очень мало относительно площади страницы и при этом
      присутствуют растровые объекты — «двухслойная ловушка»: текст вписан
      сканером или OCR-программой поверх картинки (не виден читателю, но
      вынимается через copy-paste). Обрабатываем как скан, чтобы взять
      данные из картинки, а не из скрытого текстового слоя.
    """
    text = page.get_text("text")
    if not text.strip():
        return True
    return bool(page.get_images() and _char_coverage_ratio(page) < _TEXT_COVERAGE_THRESHOLD)


def _char_coverage_ratio(page: pymupdf.Page) -> float:
    """Доля площади страницы, покрытая символьными боксами."""
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return 0.0
    data = page.get_text("rawdict")
    char_area = 0.0
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span["chars"]:
                    r = pymupdf.Rect(ch["bbox"])
                    char_area += r.width * r.height
    return char_area / page_area


def ocr_segments_for_page(
    page: pymupdf.Page,
    page_num: int,
    ocr: OCRProvider,
    dpi: int = _OCR_DPI,
) -> list[Segment]:
    """Распознать скан-страницу и вернуть сегменты с ``origin="ocr"``.

    Каждая ``OCRLine`` становится одним ``Segment``. Координаты bbox
    пересчитываются из пикселей в pt страницы: ``pt = px * 72 / dpi``.
    Целочисленное представление в локаторе (умножение на 100, округление)
    сохраняет контракт ``Anchor.locator: tuple[str|int|float, ...]`` и
    гарантирует хешируемость.
    """
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB)
    img_rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    img_bgr: np.ndarray = img_rgb[:, :, ::-1].copy()

    lines = ocr.recognize(img_bgr, dpi=dpi)

    pt_per_px = 72.0 / dpi
    label = f"стр. {page_num + 1} (скан)"
    segments: list[Segment] = []

    for line in lines:
        if not line.text.strip():
            continue
        x0_px, y0_px, x1_px, y1_px = line.bbox
        x0 = round(x0_px * pt_per_px * 100)
        y0 = round(y0_px * pt_per_px * 100)
        x1 = round(x1_px * pt_per_px * 100)
        y1 = round(y1_px * pt_per_px * 100)
        anchor = Anchor(
            fmt="pdf",
            locator=("page", page_num, "ocr", x0, y0, x1, y1),
            label=label,
        )
        segments.append(
            Segment(
                text=line.text,
                anchor=anchor,
                order=len(segments),
                origin="ocr",
            )
        )
    return segments


def _path_basename(path: str | pathlib.Path) -> str:
    return pathlib.Path(path).name
