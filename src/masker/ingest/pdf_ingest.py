"""Разбор текстового слоя PDF в плоский список Segment-ов."""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

import pymupdf

from masker.model import Anchor, Document, Segment


def ingest_pdf(path: str | pathlib.Path) -> Document:
    """Разобрать текстовый PDF и вернуть Document с сегментами по строкам."""
    doc = pymupdf.open(str(path))
    segments: list[Segment] = []
    for page_num, page in enumerate(doc):
        for locator, text, label in _iter_lines(page, page_num):
            anchor = Anchor(fmt="pdf", locator=locator, label=label)
            segments.append(Segment(text=text, anchor=anchor, order=len(segments)))
    meta = _extract_meta(doc)
    doc.close()
    return Document(path=str(path), fmt="pdf", segments=segments, meta=meta)


def _iter_lines(
    page: pymupdf.Page, page_num: int
) -> Iterator[tuple[tuple[str | int | float, ...], str, str]]:
    data = page.get_text("dict")
    label = f"стр. {page_num + 1}"
    for block in data["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            text: str = "".join(span["text"] for span in line["spans"])
            if not text.strip("\x00 \t\n\r\xa0"):
                continue
            x0, y0, x1, y1 = line["bbox"]
            locator: tuple[str | int | float, ...] = ("page", page_num, x0, y0, x1, y1)
            yield locator, text, label


def _extract_meta(doc: pymupdf.Document) -> dict[str, str]:
    keys = ("author", "title", "subject", "keywords")
    return {k: v for k in keys if (v := doc.metadata.get(k, ""))}
