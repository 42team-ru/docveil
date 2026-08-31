"""Настоящее редактирование DOCX: замена сущностей маркерами с удалением текста."""

from __future__ import annotations

import os
import pathlib
import shutil
from collections import defaultdict
from copy import deepcopy
from itertools import pairwise
from typing import cast

from docx import Document as open_docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from masker.ingest.docx_ingest import DocxLocator, iter_runs, resolve_anchor
from masker.model import Document, Entity

_NBSP = " "  # неразрывный пробел — не схлопывается в Word


def _build_marker(entity: Entity, style: str = "marker") -> str:
    marker = f"[{entity.type.value.upper()}]"
    gap = len(entity.text) - len(marker)
    if gap > 0:
        # blackbox: точки всегда получают фоновую заливку (trailing-пробелы — нет).
        # marker: NBSP приемлем, хвост белый и визуально незаметен.
        pad = "." if style == "blackbox" else _NBSP
        marker += pad * (gap * 2)
    return marker


def _set_run_shading(run: Run, fill: str) -> None:
    rPr = run._r.get_or_add_rPr()
    for old in rPr.findall(qn("w:shd")):
        rPr.remove(old)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    rPr.append(shd)


def _apply_style(run: Run, style: str) -> None:
    if style == "marker":
        _set_run_shading(run, "E8E8E8")
        run.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    else:
        _set_run_shading(run, "000000")
        run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)


def _redact_run_parts(
    paragraph: Paragraph,
    run: Run,
    run_start: int,
    entities: list[Entity],
    style: str,
) -> None:
    text = run.text
    run_end = run_start + len(text)
    overlaps = [e for e in entities if e.start < run_end and run_start < e.end]
    if not text or not overlaps:
        return

    boundaries: set[int] = {0, len(text)}
    for entity in overlaps:
        boundaries.add(max(0, entity.start - run_start))
        boundaries.add(min(len(text), entity.end - run_start))
    positions = sorted(boundaries)

    element = run._r
    parent = element.getparent()
    insert_at = parent.index(element)

    for seg_start, seg_end in pairwise(positions):
        if seg_start == seg_end:
            continue
        clone = deepcopy(element)
        cloned_run = Run(clone, paragraph)

        seg_entities = [
            e for e in overlaps if e.start < run_start + seg_end and run_start + seg_start < e.end
        ]

        if seg_entities:
            entity = seg_entities[0]
            abs_seg_start = run_start + seg_start
            if entity.start >= abs_seg_start:
                # Первый фрагмент сущности — вставляем маркер
                cloned_run.text = _build_marker(entity, style)
                _apply_style(cloned_run, style)
            else:
                # Продолжение сущности из предыдущего run — обнуляем
                cloned_run.text = ""
        else:
            cloned_run.text = text[seg_start:seg_end]

        parent.insert(insert_at, clone)
        insert_at += 1

    parent.remove(element)


def _redact_paragraph(paragraph: Paragraph, entities: list[Entity], style: str) -> None:
    offset = 0
    for run in list(iter_runs(paragraph)):
        _redact_run_parts(paragraph, run, offset, entities, style)
        offset += len(run.text)


def render_docx_redacted(
    source: str | pathlib.Path,
    destination: str | pathlib.Path,
    document: Document,
    entities: list[Entity],
    *,
    style: str = "marker",
) -> None:
    """Создать обезличенную копию DOCX: текст сущностей заменён маркерами.

    style="marker"   — светло-серый фон, маркер [ТИП] тёмным текстом.
    style="blackbox" — чёрный фон, маркер [ТИП] чёрным текстом (визуально невидим).
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")

    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    shutil.copy2(source, destination)
    doc = open_docx(str(destination))

    segments = {seg.order: seg for seg in document.segments}
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
        paragraph = resolve_anchor(doc, locator)
        if paragraph is not None:
            _redact_paragraph(paragraph, paragraph_entities, style)

    props = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "comments"):
        setattr(props, attr, "")

    doc.save(str(destination))
    os.chmod(destination, 0o600)
