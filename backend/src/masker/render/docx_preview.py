"""Диагностическая подсветка найденных сущностей в копии DOCX."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import cast

from docx import Document as open_docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from masker.highlight import (
    DEFAULT_HIGHLIGHT_BACKGROUND,
    docx_fill_color,
    parse_highlight_background,
)
from masker.ingest.docx_ingest import DocxLocator, iter_runs, resolve_anchor
from masker.model import Document, Entity


def _set_run_shading(run: Run, fill: str) -> None:
    """`w:shd` вместо `font.highlight_color`: ограничен фиксированным
    `WD_COLOR_INDEX` (16 цветов Word), а заливка принимает любой `#RRGGBB` —
    тот же приём, что и в настоящем редакторе (`docx_redact.py`), нужен и
    здесь, чтобы выбор цвета подсветки был единым, а не «маска — любой цвет,
    предпросмотр — всегда жёлтый»."""
    rPr = run._r.get_or_add_rPr()
    for old in rPr.findall(qn("w:shd")):
        rPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rPr.append(shd)


def _highlight_run_parts(
    paragraph: Paragraph, run: Run, run_start: int, entities: list[Entity], fill: str | None
) -> None:
    text = run.text
    run_end = run_start + len(text)
    overlaps = [entity for entity in entities if entity.start < run_end and run_start < entity.end]
    if not text or not overlaps:
        return

    boundaries = {0, len(text)}
    for entity in overlaps:
        boundaries.add(max(0, entity.start - run_start))
        boundaries.add(min(len(text), entity.end - run_start))
    positions = sorted(boundaries)

    element = run._r
    parent = element.getparent()
    insert_at = parent.index(element)
    for start, end in pairwise(positions):
        if start == end:
            continue
        clone = deepcopy(element)
        cloned_run = Run(clone, paragraph)
        cloned_run.text = text[start:end]
        if fill is not None and any(
            entity.start < run_start + end and run_start + start < entity.end for entity in overlaps
        ):
            _set_run_shading(cloned_run, fill)
        parent.insert(insert_at, clone)
        insert_at += 1
    parent.remove(element)


def _highlight_paragraph(paragraph: Paragraph, entities: list[Entity], fill: str | None) -> None:
    offset = 0
    for run in list(iter_runs(paragraph)):
        _highlight_run_parts(paragraph, run, offset, entities, fill)
        offset += len(run.text)


def render_docx_preview(
    source: str | Path,
    destination: str | Path,
    document: Document,
    entities: list[Entity],
    highlight_background: str | None = DEFAULT_HIGHLIGHT_BACKGROUND,
) -> None:
    """Создать копию DOCX с точной подсветкой найденных спанов.

    Текст не заменяется. Результат предназначен для проверки детектора, а не
    для передачи наружу как обезличенный документ. Цвет подсветки — тот же
    выбор, что и у маски (`highlight_background`); `None`/`"none"` убирает
    заливку совсем — тогда предпросмотр её не рисует.
    """
    source = Path(source)
    destination = Path(destination)
    fill = docx_fill_color(parse_highlight_background(highlight_background))
    preview = open_docx(str(source))
    segments = {segment.order: segment for segment in document.segments}
    order_by_locator: dict[DocxLocator, int] = {}
    by_locator: dict[DocxLocator, list[Entity]] = defaultdict(list)
    for entity in entities:
        segment = segments[entity.segment_order]
        locator = cast(DocxLocator, segment.anchor.locator)
        order_by_locator[locator] = segment.order
        by_locator[locator].append(entity)

    for locator, paragraph_entities in sorted(
        by_locator.items(), key=lambda item: order_by_locator[item[0]]
    ):
        paragraph = resolve_anchor(preview, locator)
        if paragraph is not None:
            _highlight_paragraph(paragraph, paragraph_entities, fill)

    destination.parent.mkdir(parents=True, exist_ok=True)
    preview.save(str(destination))
    destination.chmod(0o600)
