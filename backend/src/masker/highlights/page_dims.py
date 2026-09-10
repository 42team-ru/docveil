"""Размеры страниц готового PDF-артефакта — данные для нормализации bbox.

Только чтение геометрии: открыть PDF, вернуть размеры страниц в pt в том же
порядке, что и страницы в документе. Ничего не рисует и не сохраняет.

Размеры читаются из **артефакта** прогона (``masked_highlight.pdf`` или,
если его нет, ``masked_black.pdf``), а не из исходника: после квантизации
эрейз-регионов (``pdf_render._quantize_erase_rect``) содержимое страниц
меняется, а размеры страницы — нет, но правило источника единое: раз
координаты нормируем к артефакту, то и его же берём как размерный эталон.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True, slots=True)
class PageDims:
    """Размеры одной страницы в pt."""

    page: int  # 0-based
    width_pt: float
    height_pt: float


def read_page_dims(pdf_path: Path) -> list[PageDims]:
    """Открыть PDF и вернуть размеры каждой страницы в порядке 0..N-1.

    Пустой список — валидный ответ, если файл не существует (артефакт мог
    быть удалён после прогона). Ошибок формата не глотаем.
    """
    if not pdf_path.exists():
        return []
    doc = pymupdf.open(str(pdf_path))
    try:
        result: list[PageDims] = []
        for index in range(doc.page_count):
            page = doc[index]
            rect = page.rect
            result.append(
                PageDims(
                    page=index,
                    width_pt=float(rect.width),
                    height_pt=float(rect.height),
                )
            )
        return result
    finally:
        doc.close()
