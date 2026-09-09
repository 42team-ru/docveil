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
from docx.oxml.text.run import CT_R
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.shared import RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from masker.ingest.docx_ingest import DocxLocator, iter_runs, resolve_anchor
from masker.model import Document, MaskPlan, Replacement


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


def _dominant_run_rpr(paragraph: Paragraph, replacement: Replacement) -> BaseOxmlElement | None:
    """Найти `w:rPr` run'а с наибольшим перекрытием с сущностью.

    Сущность может пересекать границу run'ов, и без этого выбора маркер
    наследовал бы оформление того run'а, где физически лежит начало
    сущности, — а это может быть один символ с нетипичным кеглем или
    надстрочным/подстрочным индексом, если именно с него сущность
    начинается. Run с максимальным числом символов сущности внутри даёт
    более представительные размер, индекс и начертание для всего маркера.
    """
    best_run: Run | None = None
    best_overlap = -1
    offset = 0
    for run in iter_runs(paragraph):
        text = run.text
        run_start = offset
        run_end = offset + len(text)
        overlap = min(run_end, replacement.entity.end) - max(run_start, replacement.entity.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_run = run
        offset = run_end
    if best_run is None:
        return None
    rPr = best_run._r.find(qn("w:rPr"))
    return deepcopy(rPr) if rPr is not None else None


def _apply_dominant_rpr(run_element: CT_R, template_rPr: BaseOxmlElement | None) -> None:
    """Заменить `w:rPr` клонированного run'а на копию доминирующего.

    Действует единообразно и для найденного, и для отсутствующего `w:rPr`:
    если у доминирующего run'а форматирования нет (используются умолчания
    стиля/абзаца), маркер тоже не должен унаследовать чужое форматирование
    run'а, из которого физически вырезан текущий сегмент.
    """
    existing = run_element.find(qn("w:rPr"))
    if existing is not None:
        run_element.remove(existing)
    if template_rPr is not None:
        run_element.insert(0, deepcopy(template_rPr))


def _redact_run_parts(
    paragraph: Paragraph,
    run: Run,
    run_start: int,
    replacements: list[Replacement],
    style: str,
    templates: dict[int, BaseOxmlElement | None],
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
                # Первый фрагмент сущности — вставляем компактный маркер
                # плана как есть, без символьного паддинга (см. докстринг
                # `render_docx_redacted` про отказ от совпадения ширины).
                _apply_dominant_rpr(clone, templates[id(replacement)])
                cloned_run.text = replacement.marker
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
    # Доминирующий run считаем по исходному, ещё не тронутому абзацу —
    # для всех замен сразу, до того как цикл ниже начнёт его мутировать.
    templates = {id(r): _dominant_run_rpr(paragraph, r) for r in replacements}
    offset = 0
    for run in list(iter_runs(paragraph)):
        _redact_run_parts(paragraph, run, offset, replacements, style, templates)
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

    Маркер вставляется как есть, без символьного паддинга пробелами или
    точками до длины исходного значения (М2). Такой паддинг раньше держался
    на комментарии, который противоречил коду: заявленный «неразрывный
    пробел» на деле был обычным U+0020 и схлопывался Word'ом при открытии,
    то есть не решал заявленную задачу. Но и рабочий NBSP её бы не решил:
    число символов не равно ширине пропорционального шрифта, поэтому
    «добить пробелами/точками до длины оригинала» не даёт совпадения ширины
    в принципе — это была защита, создающая иллюзию защиты.

    Продуктовое решение: пиксельное совпадение вёрстки DOCX после замены
    текста разной длины не обещается. Обязательно только сохранение
    структуры — абзацы, строки таблиц, ячейки, листы остаются на месте, а
    перетекание текста между строками/страницами из-за иной длины маркера
    — ожидаемое и допустимое поведение редактируемого формата. Для случаев,
    где нужна неизменная геометрия страницы, у пайплайна есть PDF-рендер
    (`render/pdf_render.py`) с `apply_redactions()`, а не эмуляция фиксированной
    ширины в DOCX.

    Стиль маркера (заливка, цвет текста) клонируется вместе с формированием
    самого run'а, но исходное форматирование текста — кегль, надстрочный/
    подстрочный индекс — наследуется от run'а с наибольшим перекрытием с
    сущностью, а не от первого физического run'а: сущность может начинаться
    в run'е из одного нетипично оформленного символа (см. `_dominant_run_rpr`).

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
