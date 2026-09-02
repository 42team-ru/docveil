"""Диагностика сохранности текстового слоя PDF вне замен (план T2.2.2, шаг 4).

Обосновано Д10 (`docs/plans/T2.2.2-render-and-recall.md`): прямоугольник
редакции, посчитанный по боксам одной строки, по вертикали иногда залезал
на соседнюю строку, и ``apply_redactions`` стирал чужие глифы, попавшие в
этот прямоугольник по пересечению. Шаг 3 того же плана обрезает
прямоугольник по полосе перекрытия, но единственное доказательство, что
обрезка действительно чинит дефект, а не просто выглядит правдоподобно, —
метрика, которая была красной на коде до шага 3 и стала зелёной после.

``layout_diff`` сравнивает не байты и не форматирование, а последовательность
непробельных символов: ожидаемый остаток строится из текста исходной
страницы (``page_chars``) с вычтенными символьными диапазонами
``Replacement`` этой страницы, фактический — из текста страницы артефакта,
из которого дополнительно вычтены вхождения маркеров плана. Сравнение по
непробельным символам, а не байт в байт, — риск Р9 плана: PyMuPDF имеет
право переставить пробелы вокруг вставленного текста, это не расхождение
вёрстки.
"""

from __future__ import annotations

import pathlib
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

import pymupdf

from masker.ingest.pdf_ingest import page_chars
from masker.model import ArtifactLayout, MaskPlan

#: Символы, не участвующие в сравнении — PyMuPDF имеет право переставить
#: пробелы вокруг вставленного текста, это не расхождение вёрстки (риск Р9).
_WHITESPACE = " \t\n\r\xa0\x00"
#: Ширина контекста вокруг первого расхождения в человекочитаемом отчёте.
_CONTEXT = 12


@dataclass(frozen=True, slots=True)
class LayoutDiff:
    """Результат посимвольного сравнения текстового слоя вне замен одного PDF.

    ``expected_chars``/``actual_chars`` — длины сравниваемых непробельных
    последовательностей целиком (для контекста, не порог сами по себе).
    ``removed``/``inserted`` — символы, потерянные/появившиеся сверх
    ожидаемого, посчитанные ``difflib.SequenceMatcher`` по опкодам
    ``delete``/``insert``/``replace``. ``pages`` — номера страниц (0-based)
    с расхождением, ``first_diff`` — первое расхождение текстом.
    """

    expected_chars: int
    actual_chars: int
    removed: int
    inserted: int
    pages: tuple[int, ...]
    first_diff: str = ""


def _strip_whitespace(text: str) -> str:
    return "".join(ch for ch in text if ch not in _WHITESPACE)


def _strip_markers(text: str, markers: tuple[str, ...]) -> str:
    """Убрать вхождения маркеров плана перед сравнением.

    Только полный маркер — короткая метка типа лестницы отступления
    (``mask/labels.py``) сюда намеренно не подставляется: метрика меряет
    потерю чужого текста (``removed``), а не появление своего
    (``inserted``), и порог ворот (шаг 5) стоит только на ``removed``.
    """
    for marker in markers:
        if marker:
            text = text.replace(marker, "")
    return text


def _expected_ranges_by_page(plan: MaskPlan) -> dict[int, list[tuple[int, int]]]:
    ranges: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for replacement in plan.replacements:
        if replacement.anchor.fmt != "pdf":
            continue
        _, page_num, seg_start, _seg_end = replacement.anchor.locator
        abs_start = int(seg_start) + replacement.entity.start
        abs_end = int(seg_start) + replacement.entity.end
        ranges[int(page_num)].append((abs_start, abs_end))
    return ranges


def _remove_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return text
    kept: list[str] = []
    cursor = 0
    for start, end in sorted(ranges):
        start = max(start, cursor)
        end = max(end, start)
        kept.append(text[cursor:start])
        cursor = max(cursor, end)
    kept.append(text[cursor:])
    return "".join(kept)


def layout_diff(
    source_pdf: str | pathlib.Path,
    artifact_pdf: str | pathlib.Path,
    plan: MaskPlan,
    *,
    markers: tuple[str, ...] = (),
) -> LayoutDiff:
    """Сравнить текстовый слой ``artifact_pdf`` с ожидаемым остатком ``source_pdf``.

    Ожидаемый остаток страницы — её текст (``page_chars``) минус символьные
    диапазоны ``Replacement`` этой страницы. Фактический — текст той же
    страницы артефакта минус вхождения ``markers``. Обе последовательности
    схлопываются к непробельным символам и сравниваются
    ``difflib.SequenceMatcher`` — детерминированным, без ``random``.
    """
    source_doc = pymupdf.open(str(source_pdf))
    artifact_doc = pymupdf.open(str(artifact_pdf))
    try:
        ranges_by_page = _expected_ranges_by_page(plan)
        pages_with_diff: list[int] = []
        total_expected = 0
        total_actual = 0
        total_removed = 0
        total_inserted = 0
        first_diff = ""

        for page_num in range(len(source_doc)):
            source_text = page_chars(source_doc[page_num]).text
            expected = _strip_whitespace(
                _remove_ranges(source_text, ranges_by_page.get(page_num, []))
            )
            actual_text = artifact_doc[page_num].get_text() if page_num < len(artifact_doc) else ""
            actual = _strip_whitespace(_strip_markers(actual_text, markers))

            total_expected += len(expected)
            total_actual += len(actual)
            if expected == actual:
                continue

            matcher = SequenceMatcher(None, expected, actual, autojunk=False)
            page_removed = 0
            page_inserted = 0
            page_first_diff = ""
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    continue
                if tag in ("delete", "replace"):
                    page_removed += i2 - i1
                if tag in ("insert", "replace"):
                    page_inserted += j2 - j1
                if not page_first_diff:
                    page_first_diff = (
                        f"стр. {page_num + 1}: ожидалось "
                        f"…{expected[max(0, i1 - _CONTEXT) : i2 + _CONTEXT]}…, "
                        f"получено …{actual[max(0, j1 - _CONTEXT) : j2 + _CONTEXT]}…"
                    )
            if page_removed or page_inserted:
                pages_with_diff.append(page_num)
                total_removed += page_removed
                total_inserted += page_inserted
                if not first_diff:
                    first_diff = page_first_diff

        return LayoutDiff(
            expected_chars=total_expected,
            actual_chars=total_actual,
            removed=total_removed,
            inserted=total_inserted,
            pages=tuple(pages_with_diff),
            first_diff=first_diff,
        )
    finally:
        source_doc.close()
        artifact_doc.close()


def artifact_layout(
    source_pdf: str | pathlib.Path,
    artifact_pdf: str | pathlib.Path,
    plan: MaskPlan,
    *,
    markers: tuple[str, ...] = (),
) -> ArtifactLayout:
    """``layout_diff`` в форме, которую кладёт в отчёт ``ValidateAgent``."""
    diff = layout_diff(source_pdf, artifact_pdf, plan, markers=markers)
    return ArtifactLayout(
        artifact=pathlib.Path(artifact_pdf).name,
        removed_chars=diff.removed,
        inserted_chars=diff.inserted,
        pages=diff.pages,
        first_diff=diff.first_diff,
    )
