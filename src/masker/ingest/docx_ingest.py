"""Разбор DOCX в `Document`. T1.1 + T1.11.

Сегмент — непустой абзац основного текста (`w:body/w:p`) или прямой абзац
ячейки верхнеуровневой таблицы. Якорь тела — `("body", para_idx)`, где
`para_idx` — физический индекс абзаца в `doc.paragraphs`: пропущенные пустые
абзацы физически существуют, и рендер обязан находить абзац по индексу, а не
по счётчику непустых.

Обход `w:body` держит два независимых счётчика: `para_idx` двигается только
на прямых `w:p`, `tbl_idx` — только на прямых `w:tbl`. Другие блочные элементы
не сдвигают ни один счётчик и не обходятся рекурсивно. Ячейки таблиц идём по
`tr_lst`/`tc_lst`, а не через `row.cells`: при объединениях python-docx
возвращает один и тот же `w:tc` несколько раз.

Номер run'а в якорь не входит намеренно: сущность может пересекать границу
run'ов («ИНН 36» + «62103003» — обычное дело после правок в Word), и одним
индексом она не адресуется. Рендер получает по якорю абзац и сам вычисляет
покрывающие run'ы по `Entity.start/end` через `iter_runs`.

Вложенные таблицы, колонтитулы и сноски в этот разбор не входят.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator

from docx import Document as open_docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.text.run import CT_R
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from masker.model import Anchor, Document, Segment

#: Часть документа, которую обходим. Первый элемент якоря — дискриминатор:
#: T1.12 добавит "header", "footer", не трогая уже выданные якоря.
PART_BODY = "body"
PART_TABLE = "table"

DocxLocator = tuple[str | int, ...]

_BODY_PARAGRAPH_TAG = qn("w:p")
_BODY_TABLE_TAG = qn("w:tbl")
_BODY_SECTPR_TAG = qn("w:sectPr")


def iter_runs(paragraph: Paragraph) -> list[Run]:
    """Runs абзаца в порядке документа, включая runs внутри гиперссылок.

    `paragraph.runs` отдаёт только прямых детей `w:p` и теряет текст
    гиперссылок, а `paragraph.text` их включает. Единственная форма, при
    которой смещения сегмента совпадают с обходом рендера, — эта:
    `"".join(r.text for r in iter_runs(p)) == p.text`.
    """
    elements: list[CT_R] = paragraph._p.xpath("./w:r | ./w:hyperlink/w:r")
    return [Run(r, paragraph) for r in elements]


def iter_body_blocks(doc: DocxDocument) -> Iterator[tuple[DocxLocator, Paragraph]]:
    """Абзацы тела и верхнеуровневых таблиц в порядке чтения.

    Пустые абзацы тоже возвращаются: фильтр по `strip()` живёт в
    `ingest_docx`, а индексы в локаторах остаются физическими.
    """
    para_idx = 0
    tbl_idx = 0
    for child in doc._element.body.iterchildren():
        if not isinstance(child.tag, str):
            continue
        if child.tag == _BODY_PARAGRAPH_TAG:
            yield (PART_BODY, para_idx), Paragraph(child, doc)
            para_idx += 1
            continue
        if child.tag == _BODY_TABLE_TAG:
            table = Table(child, doc)
            for row_idx, tr in enumerate(table._tbl.tr_lst):
                for cell_idx, tc in enumerate(tr.tc_lst):
                    cell = _Cell(tc, table)
                    for cell_para_idx, paragraph in enumerate(tc.p_lst):
                        yield (
                            (
                                PART_TABLE,
                                tbl_idx,
                                row_idx,
                                cell_idx,
                                cell_para_idx,
                            ),
                            Paragraph(paragraph, cell),
                        )
            tbl_idx += 1


def resolve_anchor(doc: DocxDocument, locator: DocxLocator) -> Paragraph | None:
    """Найти абзац DOCX по локатору сегмента."""
    if len(locator) == 2 and locator[0] == PART_BODY and isinstance(locator[1], int):
        para_idx = locator[1]
        if 0 <= para_idx < len(doc.paragraphs):
            return doc.paragraphs[para_idx]
        return None

    if (
        len(locator) == 5
        and locator[0] == PART_TABLE
        and all(isinstance(item, int) for item in locator[1:])
    ):
        _, tbl_idx, row_idx, cell_idx, table_para_idx = locator
        assert isinstance(tbl_idx, int)
        assert isinstance(row_idx, int)
        assert isinstance(cell_idx, int)
        assert isinstance(table_para_idx, int)
        if not 0 <= tbl_idx < len(doc.tables):
            return None
        table = doc.tables[tbl_idx]
        if not 0 <= row_idx < len(table._tbl.tr_lst):
            return None
        tr = table._tbl.tr_lst[row_idx]
        if not 0 <= cell_idx < len(tr.tc_lst):
            return None
        tc = tr.tc_lst[cell_idx]
        if not 0 <= table_para_idx < len(tc.p_lst):
            return None
        return Paragraph(tc.p_lst[table_para_idx], _Cell(tc, table))

    return None


def count_skipped_body_blocks(doc: DocxDocument) -> int:
    """Сколько прямых детей `w:body` не входит в текущий DOCX-обход."""
    skipped = 0
    for child in doc._element.body.iterchildren():
        if not isinstance(child.tag, str):
            continue
        if child.tag not in {_BODY_PARAGRAPH_TAG, _BODY_TABLE_TAG, _BODY_SECTPR_TAG}:
            skipped += 1
    return skipped


def count_nested_tables(doc: DocxDocument) -> int:
    """Посчитать вложенные таблицы, которые T1.11 намеренно не сегментирует."""
    return sum(len(table._tbl.xpath(".//w:tbl")) for table in doc.tables)


def ingest_docx(path: str | pathlib.Path) -> Document:
    """Разобрать `.docx` в `Document` с сегментами и якорями."""
    path = pathlib.Path(path)
    doc = open_docx(str(path))

    segments: list[Segment] = []
    for locator, para in iter_body_blocks(doc):
        text = para.text
        if not text.strip():
            continue
        label = _anchor_label(locator)
        segments.append(
            Segment(
                text=text,
                anchor=Anchor(
                    fmt="docx",
                    locator=locator,
                    label=label,
                ),
                order=len(segments),
            )
        )

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


def _anchor_label(locator: DocxLocator) -> str:
    if len(locator) == 2 and locator[0] == PART_BODY and isinstance(locator[1], int):
        return f"абзац {locator[1] + 1}"
    if (
        len(locator) == 5
        and locator[0] == PART_TABLE
        and all(isinstance(item, int) for item in locator[1:])
    ):
        _, tbl_idx, row_idx, cell_idx, para_idx = locator
        assert isinstance(tbl_idx, int)
        assert isinstance(row_idx, int)
        assert isinstance(cell_idx, int)
        assert isinstance(para_idx, int)
        return (
            f"таблица {tbl_idx + 1}, строка {row_idx + 1}, "
            f"ячейка {cell_idx + 1}, абзац {para_idx + 1}"
        )
    return "неизвестный якорь"
