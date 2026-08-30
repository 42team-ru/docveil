"""Рендер PDF: неразрушающий preview и настоящее редактирование."""

from __future__ import annotations

import os
import pathlib
from collections import defaultdict

import pymupdf

from masker.model import Document, Entity

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
    entities: list[Entity],
    *,
    style: str = "marker",
) -> None:
    """Удалить сущности из content-stream и вставить заглушки.

    style="marker"   — белый фон, маркер [ТИП] вписан по ширине прямоугольника.
    style="blackbox" — чёрный прямоугольник; маркер вставляется белым цветом
                       (визуально не читаем, но заменяет исходный текст в
                       content-stream — copy-paste и поиск отдают маркер).
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")

    source_path = pathlib.Path(source_path)
    dest_path = pathlib.Path(dest_path)
    doc = pymupdf.open(str(source_path))
    font = pymupdf.Font(fontfile=str(_FONT_FILE))

    # Сгруппировать по страницам; поиск rects до любых изменений документа.
    by_page: dict[int, list[tuple[pymupdf.Rect, str]]] = defaultdict(list)
    for entity in entities:
        page_num, clip = _parse_locator(document.segments[entity.segment_order].anchor.locator)
        page = doc[page_num]
        marker = _build_marker(entity)
        for rect in page.search_for(entity.text, clip=clip):
            by_page[page_num].append((rect, marker))

    fill_color = (0.0, 0.0, 0.0) if style == "blackbox" else (1.0, 1.0, 1.0)
    text_color = (1.0, 1.0, 1.0) if style == "blackbox" else (0.20, 0.20, 0.20)

    for page_num, redactions in by_page.items():
        page = doc[page_num]
        page.insert_font(fontname=_FONT_NAME, fontfile=str(_FONT_FILE))
        for rect, _ in redactions:
            page.add_redact_annot(rect, fill=fill_color)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        for rect, marker in redactions:
            size = _fit_fontsize(font, rect, marker)
            box = pymupdf.Rect(rect.x0, rect.y0 - 1, rect.x1 + 2, rect.y1 + 2)
            page.insert_textbox(
                box,
                marker,
                fontname=_FONT_NAME,
                fontfile=str(_FONT_FILE),
                fontsize=size,
                color=text_color,
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


def _build_marker(entity: Entity) -> str:
    return f"[{entity.type.value.upper()}]"
