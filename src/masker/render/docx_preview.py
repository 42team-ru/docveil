"""Диагностическая подсветка найденных сущностей в копии DOCX."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from itertools import pairwise
from pathlib import Path

from docx import Document as open_docx
from docx.enum.text import WD_COLOR_INDEX
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from masker.ingest.docx_ingest import iter_runs
from masker.model import Document, Entity


def _highlight_run_parts(
    paragraph: Paragraph, run: Run, run_start: int, entities: list[Entity]
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
        if any(
            entity.start < run_start + end and run_start + start < entity.end for entity in overlaps
        ):
            cloned_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        parent.insert(insert_at, clone)
        insert_at += 1
    parent.remove(element)


def _highlight_paragraph(paragraph: Paragraph, entities: list[Entity]) -> None:
    offset = 0
    for run in list(iter_runs(paragraph)):
        _highlight_run_parts(paragraph, run, offset, entities)
        offset += len(run.text)


def render_docx_preview(
    source: str | Path,
    destination: str | Path,
    document: Document,
    entities: list[Entity],
) -> None:
    """Создать копию DOCX с точной жёлтой подсветкой найденных спанов.

    Текст не заменяется. Результат предназначен для проверки детектора, а не
    для передачи наружу как обезличенный документ.
    """
    source = Path(source)
    destination = Path(destination)
    preview = open_docx(str(source))
    segments = {segment.order: segment for segment in document.segments}
    by_paragraph: dict[int, list[Entity]] = defaultdict(list)
    for entity in entities:
        segment = segments[entity.segment_order]
        part, paragraph_index = segment.anchor.locator
        if part != "body" or not isinstance(paragraph_index, int):
            continue
        by_paragraph[paragraph_index].append(entity)

    for paragraph_index, paragraph_entities in sorted(by_paragraph.items()):
        _highlight_paragraph(preview.paragraphs[paragraph_index], paragraph_entities)

    destination.parent.mkdir(parents=True, exist_ok=True)
    preview.save(str(destination))
    destination.chmod(0o600)
