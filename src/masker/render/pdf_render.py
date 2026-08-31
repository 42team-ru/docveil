"""Рендер PDF: неразрушающий preview и настоящее редактирование."""

from __future__ import annotations

import os
import pathlib
from collections import defaultdict

import pymupdf

from masker.model import Document, Entity, MaskPlan, Replacement

_FONT_FILE: pathlib.Path = pathlib.Path(__file__).parent.parent / "data" / "DejaVuSans.ttf"
_FONT_NAME = "cyr"


def render_pdf_preview(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    entities: list[Entity],
) -> None:
    """Создать копию PDF с жёлтыми highlight-аннотациями; исходный текст сохранён."""
    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    doc = pymupdf.open(str(source_path))
    for entity in entities:
        page_num, clip = _parse_locator(document.segments[entity.segment_order].anchor.locator)
        page = doc[page_num]
        for rect in page.search_for(entity.text, clip=clip):
            annot = page.add_highlight_annot(rect)
            annot.update()
    doc.save(str(dest_path))
    doc.close()
    os.chmod(dest_path, 0o600)


def render_pdf_redacted(
    source_path: str | pathlib.Path,
    dest_path: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
) -> None:
    """Удалить сущности из content-stream и вставить заглушки с маркерами плана.

    style="marker"   — белый фон, маркер плана вписан по ширине прямоугольника.
    style="blackbox" — чёрный прямоугольник без текста; исходный текст полностью
                       удалён из content-stream, маркер не вставляется.

    ``document`` рендеру для поиска места замены не нужен — см. докстринг
    ``render_docx_redacted``: место уже посчитано один раз ``PlanAgent`` и
    приходит в ``plan.replacements[].anchor``. Параметр оставлен для
    единообразия сигнатуры с ``render_pdf_preview``.
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")

    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    doc = pymupdf.open(str(source_path))
    font = pymupdf.Font(fontfile=str(_FONT_FILE)) if style == "marker" else None

    # Сгруппировать по страницам; поиск rects до любых изменений документа.
    by_page: dict[int, list[tuple[pymupdf.Rect, str]]] = defaultdict(list)
    for replacement in plan.replacements:
        page_num, clip = _parse_locator(replacement.anchor.locator)
        page = doc[page_num]
        marker = _build_marker(replacement)
        for rect in page.search_for(replacement.entity.text, clip=clip):
            by_page[page_num].append((rect, marker))

    fill_color = (0.0, 0.0, 0.0) if style == "blackbox" else (1.0, 1.0, 1.0)

    for page_num, redactions in by_page.items():
        page = doc[page_num]
        for rect, _ in redactions:
            page.add_redact_annot(rect, fill=fill_color)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        if style == "marker":
            assert font is not None
            page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
            for rect, marker in redactions:
                size = _fit_fontsize(font, rect, marker)
                box = pymupdf.Rect(rect.x0, rect.y0 - 1, rect.x1 + 2, rect.y1 + 2)
                page.insert_textbox(
                    box,
                    marker,
                    fontname=_FONT_NAME,
                    fontfile=str(_FONT_FILE),
                    fontsize=size,
                    color=(0.20, 0.20, 0.20),
                    align=pymupdf.TEXT_ALIGN_LEFT,
                )

    doc.set_metadata({})
    doc.del_xml_metadata()
    doc.save(str(dest_path), garbage=4, deflate=True)
    doc.close()
    os.chmod(dest_path, 0o600)


def _parse_locator(locator: tuple[str | int | float, ...]) -> tuple[int, pymupdf.Rect]:
    _, page_num, x0, y0, x1, y1 = locator
    return int(page_num), pymupdf.Rect(float(x0), float(y0), float(x1), float(y1))


def _fit_fontsize(font: pymupdf.Font, rect: pymupdf.Rect, text: str) -> float:
    for size in (10, 9, 8, 7, 6, 5, 4):
        if font.text_length(text, fontsize=float(size)) <= rect.width:
            return float(size)
    return 4.0


def _build_marker(replacement: Replacement) -> str:
    """Строка маркера для вставки в PDF.

    Паддинг символами, в отличие от `render/docx_redact.py`, здесь не нужен:
    `_fit_fontsize` вписывает маркер любой длины в ширину прямоугольника
    подбором размера шрифта, а не дополнением текста.
    """
    return replacement.marker
