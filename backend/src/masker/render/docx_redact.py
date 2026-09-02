"""Настоящее редактирование DOCX: замена сущностей маркерами плана с удалением текста."""

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
from masker.model import Document, MaskPlan, Replacement

_NBSP = " "  # неразрывный пробел — не схлопывается в Word


def _build_marker(replacement: Replacement, style: str = "marker") -> str:
    """Дописать паддинг к готовому маркеру плана.

    Текст маркера (например, ``[ПОСТАВЩИК-ИНН]``) приходит целиком из
    ``Replacement.marker`` — рендер больше не знает про ``EntityType`` и не
    собирает маркер сам (T1.6, `mask/agent.py`). Паддинг компенсирует
    случай, когда исходное значение длиннее маркера; если маркер уже
    длиннее исходного значения — обычный случай для маркеров с ролью,
    например «ИНН» (10 знаков) → ``[ПОСТАВЩИК-ИНН]`` (17 знаков) — паддинг
    не добавляется и текст маркера не обрезается (см.
    `test_marker_longer_than_source_does_not_pad`).
    """
    marker = replacement.marker
    gap = len(replacement.entity.text) - len(marker)
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
    replacements: list[Replacement],
    style: str,
) -> None:
    text = run.text
    run_end = run_start + len(text)
    overlaps = [r for r in replacements if r.entity.start < run_end and run_start < r.entity.end]
    if not text or not overlaps:
        return

    boundaries: set[int] = {0, len(text)}
    for replacement in overlaps:
        boundaries.add(max(0, replacement.entity.start - run_start))
        boundaries.add(min(len(text), replacement.entity.end - run_start))
    positions = sorted(boundaries)

    element = run._r
    parent = element.getparent()
    insert_at = parent.index(element)

    for seg_start, seg_end in pairwise(positions):
        if seg_start == seg_end:
            continue
        clone = deepcopy(element)
        cloned_run = Run(clone, paragraph)

        seg_replacements = [
            r
            for r in overlaps
            if r.entity.start < run_start + seg_end and run_start + seg_start < r.entity.end
        ]

        if seg_replacements:
            replacement = seg_replacements[0]
            abs_seg_start = run_start + seg_start
            if replacement.entity.start >= abs_seg_start:
                # Первый фрагмент сущности — вставляем маркер
                cloned_run.text = _build_marker(replacement, style)
                _apply_style(cloned_run, style)
            else:
                # Продолжение сущности из предыдущего run — обнуляем
                cloned_run.text = ""
        else:
            cloned_run.text = text[seg_start:seg_end]

        parent.insert(insert_at, clone)
        insert_at += 1

    parent.remove(element)


def _redact_paragraph(paragraph: Paragraph, replacements: list[Replacement], style: str) -> None:
    offset = 0
    for run in list(iter_runs(paragraph)):
        _redact_run_parts(paragraph, run, offset, replacements, style)
        offset += len(run.text)


def render_docx_redacted(
    source: str | pathlib.Path,
    destination: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
) -> None:
    """Создать обезличенную копию DOCX: текст сущностей заменён маркерами плана.

    style="marker"   — светло-серый фон, маркер плана тёмным текстом.
    style="blackbox" — чёрный фон, маркер плана чёрным текстом (визуально невидим).

    ``document`` рендеру для поиска места замены не нужен: место уже
    посчитано один раз ``PlanAgent`` и приходит в
    ``plan.replacements[].anchor``. Параметр оставлен для единообразия
    сигнатуры с ``render_docx_preview`` и на будущее — T1.10 подключает оба
    рендера как узлы графа с общим набором аргументов.
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")

    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    shutil.copy2(source, destination)
    doc = open_docx(str(destination))

    by_locator: dict[DocxLocator, list[Replacement]] = defaultdict(list)
    for replacement in plan.replacements:
        locator = cast(DocxLocator, replacement.anchor.locator)
        by_locator[locator].append(replacement)

    # `plan.replacements` уже в текстовом порядке (контракт `MaskPlan`),
    # поэтому порядок вставки в `by_locator` и есть порядок документа —
    # отдельная сортировка по месту, как раньше через `document.segments`,
    # больше не нужна.
    for locator, paragraph_replacements in by_locator.items():
        paragraph = resolve_anchor(doc, locator)
        if paragraph is not None:
            _redact_paragraph(paragraph, paragraph_replacements, style)

    props = doc.core_properties
    for attr in ("author", "last_modified_by", "title", "subject", "keywords", "comments"):
        setattr(props, attr, "")

    doc.save(str(destination))
    os.chmod(destination, 0o600)
