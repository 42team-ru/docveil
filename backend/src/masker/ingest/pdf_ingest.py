"""Разбор текстового слоя PDF в плоский список Segment-ов.

Сегмент PDF = блок ``get_text("rawdict")`` (план T2.2.1, шаг 8, решение П1
варианта A): строки внутри блока склеиваются одним пробелом, якорь —
символьный диапазон ``("page", page_num, char_start, char_end)`` в тексте,
который строит ``page_chars`` для всей страницы. Раньше сегмент был одной
строкой, и сущность через перенос строки (``Общество с`` + перенос +
``Ограниченной Ответственностью «...»``) физически не могла стать одной
``Entity`` — ``Entity.start``/``end`` по контракту ``model.py`` локальны
одному сегменту (Д3).

``page_chars`` — общий строитель для ingest'а и рендера
(``render/pdf_render.py``): обе стороны обязаны видеть одну и ту же
раскладку символов по странице, иначе рендер посчитает смещение не в тот
глиф (риск Р4 плана T2.2.1). Единственный проход по ``rawdict`` —
``_walk_page`` — используется и им, и построением сегментов, чтобы эти
две задачи не разъехались в две независимые реализации обхода.

Блок иногда оказывается большим (десятки строк, оба контрагента в одном
блоке таблицы реквизитов) — риск Р3: ``ProfileAgent`` кластеризует по
близости внутри сегмента, и один блок на обе стороны склеил бы их профили.
Поэтому блок дополнительно режется перед строкой, начинающейся с номера
пункта договора (``1.``, ``2.3.``) — деталь, извлекаемая из структуры
документа, а не подобранный порог длины.

Пер-страничный роутинг скан-страниц введён в T2.3/O3: если ``ocr`` передан
в ``ingest_pdf``, каждая страница проверяется через ``_page_is_scan`` из
``scan_ingest``; скан-страницы обрабатываются через OCR, текстовые —
существующим путём. Без ``ocr`` поведение не меняется.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

import pymupdf

from masker.ingest.scan_ingest import _page_is_scan, ocr_segments_for_page
from masker.model import Anchor, Document, Segment
from masker.ocr.provider import OCRProvider

#: Символы, которые не считаются видимым текстом на конце блока/строки —
#: та же логика, что раньше отбрасывала пустые строки.
_BLANK_CHARS = "\x00 \t\n\r\xa0"

#: Разбиение блока перед строкой-началом пункта договора (`1.`, `2.3.4.`) —
#: риск Р3 плана T2.2.1: без этого блок реквизитов на 60+ строк смешивает
#: обе стороны договора в один профиль. Порог — не длина, а структура.
_CLAUSE_START_RE = re.compile(r"^\s*\d+(?:\.\d+)*\.")


@dataclass(frozen=True, slots=True)
class PageChars:
    """Текст страницы, бокс и номер строки каждого символа (план T2.2.2, шаг 2).

    Инвариант: ``len(text) == len(boxes) == len(line_ids)`` всегда. Номер
    строки сквозной по странице (не сбрасывается на границе блока) — так
    рендер (``render/pdf_render.py``) может обрезать прямоугольник редакции
    строго по своей строке, определённой из ingest'а, а не угадывать её по
    координате (Д10 плана T2.2.2: угадывание по координате на реальном
    документе схлопнуло прямоугольник и сущность утекла). Символу-склейке
    строк (``Rect(0, 0, 0, 0)``) присваивается номер строки, которую он
    закрывает, а не следующей.
    """

    text: str
    boxes: tuple[pymupdf.Rect, ...]
    line_ids: tuple[int, ...]


def page_chars(page: pymupdf.Page) -> PageChars:
    """Текст страницы, бокс и номер строки каждого символа, один обход."""
    text, boxes, line_ids, _ = _walk_page(page)
    return PageChars(text=text, boxes=boxes, line_ids=line_ids)


def ingest_pdf(path: str | pathlib.Path, ocr: OCRProvider | None = None) -> Document:
    """Разобрать PDF и вернуть Document с сегментами.

    Без ``ocr``: все страницы трактуются как текстовые (прежнее поведение).
    С ``ocr``: пер-страничный роутинг — скан-страницы идут через OCR,
    текстовые — через существующий ``_walk_page``-путь.
    """
    doc = pymupdf.open(str(path))
    segments: list[Segment] = []
    for page_num, page in enumerate(doc):
        if ocr is not None and _page_is_scan(page):
            ocr_segs = ocr_segments_for_page(page, page_num, ocr)
            for seg in ocr_segs:
                segments.append(Segment(seg.text, seg.anchor, len(segments), seg.origin))
        else:
            text, _, _, segment_ranges = _walk_page(page)
            label = f"стр. {page_num + 1}"
            for char_start, char_end in segment_ranges:
                segment_text = text[char_start:char_end]
                if not segment_text.strip(_BLANK_CHARS):
                    continue
                anchor = Anchor(
                    fmt="pdf", locator=("page", page_num, char_start, char_end), label=label
                )
                segments.append(Segment(text=segment_text, anchor=anchor, order=len(segments)))
    meta = _extract_meta(doc)
    doc.close()
    return Document(path=str(path), fmt="pdf", segments=segments, meta=meta)


def _walk_page(
    page: pymupdf.Page,
) -> tuple[str, tuple[pymupdf.Rect, ...], tuple[int, ...], tuple[tuple[int, int], ...]]:
    """Единственный обход страницы: текст, боксы символов, номера строк,
    границы сегментов.

    И ``page_chars`` (нужны текст, боксы и номера строк — используется
    рендером), и ``ingest_pdf`` (нужны ещё и границы сегментов) читают ровно
    этот список — см. докстринг модуля про риск Р4. Номер строки — сквозной
    счётчик по странице, не по блоку: инкрементируется после каждой
    физической строки ``rawdict``, поэтому у двух соседних строк одного
    блока номера всегда отличаются ровно на 1.
    """
    data = page.get_text("rawdict")
    chars: list[str] = []
    boxes: list[pymupdf.Rect] = []
    line_ids: list[int] = []
    segment_ranges: list[tuple[int, int]] = []
    line_id = 0
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        segment_start = len(chars)
        for line in block["lines"]:
            line_start = len(chars)
            for span in line["spans"]:
                for ch in span["chars"]:
                    chars.append(ch["c"])
                    boxes.append(pymupdf.Rect(ch["bbox"]))
                    line_ids.append(line_id)
            line_text = "".join(chars[line_start:])
            if line_start > segment_start and _CLAUSE_START_RE.match(line_text):
                segment_ranges.append((segment_start, line_start))
                segment_start = line_start
            # Склейка строк внутри блока — пробел без места на странице,
            # закрывающий строку `line_id`, а не открывающий следующую.
            chars.append(" ")
            boxes.append(pymupdf.Rect(0.0, 0.0, 0.0, 0.0))
            line_ids.append(line_id)
            line_id += 1
        segment_ranges.append((segment_start, len(chars)))
    return "".join(chars), tuple(boxes), tuple(line_ids), tuple(segment_ranges)


def _extract_meta(doc: pymupdf.Document) -> dict[str, str]:
    keys = ("author", "title", "subject", "keywords")
    return {k: v for k in keys if (v := doc.metadata.get(k, ""))}
