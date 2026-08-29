"""Разбор DOCX в `Document`. T1.1.

Якорь сегмента — `(part, para_idx, run_idx)`, где `part` различает основной
текст, таблицы, колонтитулы и сноски. По якорю рендер находит тот самый run
и разрезает его, не трогая остальное форматирование.

Таблицы обходятся по ячейкам, каждый абзац ячейки — отдельный сегмент
с `is_table=True`. Пустые абзацы пропускаются: маскировать в них нечего,
а порядковые номера сегментов должны оставаться плотными.
"""

from __future__ import annotations

import pathlib

from docx import Document as open_docx
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from masker.model import Anchor, Document, Segment

#: Части документа, которые обходим. Порядок фиксирован — от него зависит
#: `Segment.order`, а значит и детерминизм всего пайплайна.
PART_BODY = "body"
PART_TABLE = "table"
PART_HEADER = "header"
PART_FOOTER = "footer"


def _paragraph_segments(
    para: Paragraph,
    part: str,
    locator_head: tuple[object, ...],
    order: int,
    is_table: bool,
    label: str,
) -> list[Segment]:
    """Один абзац — один сегмент, если в нём есть текст."""
    text = para.text
    if not text.strip():
        return []
    return [
        Segment(
            text=text,
            anchor=Anchor(fmt="docx", locator=(part, *locator_head), label=label),
            order=order,
            is_table=is_table,
        )
    ]


def _iter_body(doc: DocxDocument) -> list[tuple[str, tuple[object, ...], Paragraph, bool, str]]:
    """Абзацы основного текста и ячеек таблиц в порядке их следования.

    python-docx не даёт готового обхода «тело в исходном порядке», поэтому
    идём по XML-детям тела и разбираем абзацы и таблицы по мере встречи.
    Иначе таблицы уехали бы в конец и `Segment.order` перестал бы
    соответствовать чтению документа.
    """
    items: list[tuple[str, tuple[object, ...], Paragraph, bool, str]] = []
    body = doc.element.body
    para_idx = table_idx = 0
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            items.append((PART_BODY, (para_idx,), para, False, f"абзац {para_idx + 1}"))
            para_idx += 1
        elif tag == "tbl":
            table = Table(child, doc)
            for r, row in enumerate(table.rows):
                for c, cell in enumerate(row.cells):
                    for q, para in enumerate(cell.paragraphs):
                        items.append(
                            (
                                PART_TABLE,
                                (table_idx, r, c, q),
                                para,
                                True,
                                f"таблица {table_idx + 1}, строка {r + 1}, столбец {c + 1}",
                            )
                        )
            table_idx += 1
    return items


def _iter_headers_footers(
    doc: DocxDocument,
) -> list[tuple[str, tuple[object, ...], Paragraph, bool, str]]:
    """Колонтитулы: реквизиты часто живут именно там, и про них забывают."""
    items: list[tuple[str, tuple[object, ...], Paragraph, bool, str]] = []
    for s, section in enumerate(doc.sections):
        for part, container, human in (
            (PART_HEADER, section.header, "верхний колонтитул"),
            (PART_FOOTER, section.footer, "нижний колонтитул"),
        ):
            for i, para in enumerate(container.paragraphs):
                items.append((part, (s, i), para, False, f"{human}, раздел {s + 1}"))
    return items


def ingest_docx(path: str | pathlib.Path) -> Document:
    """Разобрать `.docx` в `Document` с сегментами и якорями."""
    path = pathlib.Path(path)
    doc = open_docx(str(path))

    segments: list[Segment] = []
    for part, locator, para, is_table, label in _iter_body(doc) + _iter_headers_footers(doc):
        segments.extend(_paragraph_segments(para, part, locator, len(segments), is_table, label))

    props = doc.core_properties
    meta = {
        key: value
        for key, value in (
            ("author", props.author),
            ("last_modified_by", props.last_modified_by),
            ("title", props.title),
            ("subject", props.subject),
            ("comments", props.comments),
            ("category", props.category),
            ("keywords", props.keywords),
        )
        if value
    }

    return Document(path=str(path), fmt="docx", segments=segments, meta=meta)
