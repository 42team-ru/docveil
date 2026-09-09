"""Настоящее редактирование XLSX: замена сущностей маркерами плана.

Ключевой риск этого формата — не текст, а арифметика: формула, ссылающаяся
на замаскированную ячейку, восстанавливает исходное значение при первом же
пересчёте (см. AGENTS.md, «главный риск М7»). Явное решение, принятое здесь:
такая формула не пересчитывается от нового значения и не оставляется как
формула — она целиком заменяется на маркер-заглушку, ровно как обычная
замаскированная ячейка. Дешевле потерять работоспособность одной производной
формулы, чем один раз молча вернуть исходные данные пользователю.

Обнаружение зависимости — не полноценный разбор формул Excel (это отдельная
задача уровня движка электронных таблиц), а достаточный для приёмки набор
регулярок: прямые и относительные ссылки на ячейки (``B2``, ``$B$2``),
диапазоны (``B2:B10``), межлистовые ссылки (``'Лист 2'!B2``) и именованные
диапазоны (``workbook.defined_names``), с рекурсивным разворачиванием имени
в его формулу. Не покрыты: ссылки на диапазон целого столбца/строки
(``A:A``) и сводные таблицы — для них ниже отдельная защита: явный отказ
вместо тихой утечки (``XlsxPivotTableError``).
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
from collections import defaultdict
from typing import cast

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import column_index_from_string
from openpyxl.utils.cell import coordinate_from_string
from openpyxl.workbook.workbook import Workbook

from masker.ingest.xlsx_ingest import XlsxLocator, resolve_anchor
from masker.model import Document, MaskPlan, Replacement

#: Значение, которым заменяется формула, зависящая от замаскированной
#: ячейки напрямую, транзитивно (через цепочку других формул) или через
#: именованный диапазон. Не берётся из `Replacement.marker` конкретной
#: сущности намеренно: производная ячейка не хранит то же значение, что и
#: источник, — присвоить ей чужой маркер значило бы соврать в отчёте о том,
#: что здесь находится.
FORMULA_MARKER = "[ФОРМУЛА: СКРЫТО — ЗАВИСИТ ОТ ОБЕЗЛИЧЕННЫХ ДАННЫХ]"

_CELL_TOKEN = r"\$?[A-Za-z]{1,3}\$?[0-9]+"
#: Ссылка на ячейку/диапазон в формуле: либо с явным листом (`'Лист 2'!B2`,
#: `Sheet1!B2:C10`), либо без — тогда лист текущий. Отрицательные
#: look-around вокруг «голой» ссылки — защита от совпадения с хвостом
#: произвольного идентификатора (`TABLE1` не должно дать ссылку `E1`) и с
#: именем функции, оканчивающимся цифрой перед скобкой (`LOG10(`).
_REF_RE = re.compile(
    r"(?:'[^']+'|[A-Za-zА-Яа-яЁё0-9_.]+)!" + _CELL_TOKEN + r"(?::" + _CELL_TOKEN + r")?"
    r"|"
    r"(?<![A-Za-zА-Яа-яЁё0-9_$])" + _CELL_TOKEN + r"(?::" + _CELL_TOKEN + r")?"
    r"(?![A-Za-zА-Яа-яЁё0-9_(])"
)
#: Кандидат в имя именованного диапазона внутри формулы — любой
#: идентификатор, не входящий в уже найденную ссылку на ячейку и не
#: являющийся вызовом функции (сразу за ним не открывающая скобка).
_NAME_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_.]*")

#: Координата ячейки в абсолютных терминах книги: (лист, строка, столбец).
CellCoord = tuple[str, int, int]


class XlsxPivotTableError(RuntimeError):
    """Книга содержит сводную таблицу — маскирование отклонено явно.

    Сводная таблица хранит собственный кэш скопированных значений
    (`xl/pivotCache/pivotCacheRecords*.xml`), который `openpyxl` не читает
    содержательно и не перезаписывает при сохранении. Промолчать и
    выпустить файл с обычными ячейками замаскированными, а кэшем сводной —
    нет, значит гарантированно один раз отдать исходные данные тому, кто
    откроет сводную таблицу. Правило проекта «тихий неверный результат
    дороже падения» (AGENTS.md) требует здесь громкого отказа, а не
    правдоподобного, но дырявого файла — до отдельной задачи на поддержку
    очистки кэша сводных такие книги не обрабатываются вовсе.
    """


def _has_pivot_tables(workbook: Workbook) -> bool:
    """Есть ли хоть одна сводная таблица хоть на одном листе книги.

    Вынесено отдельной функцией (а не инлайном в `_reject_pivot_tables`),
    чтобы решение «есть сводная» можно было проверить в тесте изолированно
    от того, умеет ли тестовое окружение честно собрать валидный
    `xl/pivotCache/*` через `openpyxl` (на практике — не умеет).
    """
    return any(getattr(sheet, "_pivots", None) for sheet in workbook.worksheets)


def _reject_pivot_tables(workbook: Workbook) -> None:
    if _has_pivot_tables(workbook):
        raise XlsxPivotTableError(
            "книга содержит сводную таблицу — "
            "маскирование XLSX со сводными таблицами не поддержано (М7)"
        )


def _defined_names(workbook: Workbook) -> dict[str, str]:
    """Именованные диапазоны книги: имя в нижнем регистре → его формула."""
    names: dict[str, str] = {}
    for name, defined in workbook.defined_names.items():
        value = getattr(defined, "value", None)
        if isinstance(value, str):
            names[name.lower()] = value
    return names


def _expand_cell_range(cell_part: str, sheet_name: str, workbook: Workbook) -> set[CellCoord]:
    """Развернуть `B2` или `B2:C10` в конкретные координаты ячеек листа.

    Диапазон, вылезающий за пределы фактически использованных строк/
    столбцов листа (`SUM(A1:A100000)` при пяти реальных строках),
    ограничивается фактическим размером листа — иначе один такой диапазон
    в тестовой книге разворачивался бы в сотни тысяч пустых координат.
    """
    if sheet_name not in workbook.sheetnames:
        return set()
    sheet = workbook[sheet_name]
    corners = cell_part.split(":")
    rows: list[int] = []
    cols: list[int] = []
    for corner in corners:
        col_letters, row = coordinate_from_string(corner.replace("$", ""))
        rows.append(row)
        cols.append(column_index_from_string(col_letters))
    row_start, row_end = min(rows), min(max(rows), max(sheet.max_row, 1))
    col_start, col_end = min(cols), min(max(cols), max(sheet.max_column, 1))
    if row_start > row_end or col_start > col_end:
        return set()
    return {
        (sheet_name, r, c)
        for r in range(row_start, row_end + 1)
        for c in range(col_start, col_end + 1)
    }


def _split_sheet_ref(token: str) -> tuple[str | None, str]:
    if "!" not in token:
        return None, token
    sheet_part, cell_part = token.rsplit("!", 1)
    return sheet_part.strip("'"), cell_part


def resolve_formula_references(
    formula: str,
    current_sheet: str,
    workbook: Workbook,
    defined_names: dict[str, str],
    _seen_names: frozenset[str] = frozenset(),
) -> set[CellCoord]:
    """Все ячейки, на которые ссылается формула — напрямую или через имя.

    Публичная функция (а не приватная), потому что это единственная точка,
    которую стоит тестировать изолированно от файла на диске — она же
    покрывает и прямую ссылку, и диапазон, и межлистовую ссылку, и
    именованный диапазон, разворачиваемый рекурсивно.
    """
    refs: set[CellCoord] = set()
    consumed_spans: list[tuple[int, int]] = []
    for match in _REF_RE.finditer(formula):
        consumed_spans.append(match.span())
        sheet_part, cell_part = _split_sheet_ref(match.group())
        sheet_name = sheet_part or current_sheet
        refs |= _expand_cell_range(cell_part, sheet_name, workbook)

    for match in _NAME_TOKEN_RE.finditer(formula):
        if any(match.start() >= start and match.end() <= end for start, end in consumed_spans):
            continue
        if formula[match.end() : match.end() + 1] == "(":
            continue  # вызов функции, не имя диапазона
        name = match.group().lower()
        if name in defined_names and name not in _seen_names:
            refs |= resolve_formula_references(
                defined_names[name],
                current_sheet,
                workbook,
                defined_names,
                _seen_names | {name},
            )
    return refs


def _neutralize_dependent_formulas(workbook: Workbook, masked: set[CellCoord]) -> set[CellCoord]:
    """Обезвредить формулы, зависящие от `masked`, транзитивно до неподвижной точки.

    После первой замены зависимой формулы на `FORMULA_MARKER` эта ячейка
    сама становится «замаскированной» и включается в `masked` — формула,
    ссылающаяся уже на неё (цепочка `E5 = D7 + 5`, `D7 = B2 * 1.2`, `B2`
    замаскирован), тоже обязана быть обезврежена, а не остаться с
    вычисляемой ошибкой на месте раскрытого значения.
    """
    defined_names = _defined_names(workbook)
    converted: set[CellCoord] = set()
    changed = True
    while changed:
        changed = False
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                for cell in row:
                    if cell.data_type != "f" or not isinstance(cell.value, str):
                        continue
                    coord = (sheet.title, cell.row, cell.column)
                    if coord in converted:
                        continue
                    refs = resolve_formula_references(
                        cell.value.lstrip("="), sheet.title, workbook, defined_names
                    )
                    if refs & masked:
                        cell.value = FORMULA_MARKER
                        converted.add(coord)
                        masked.add(coord)
                        changed = True
    return converted


def _apply_cell_replacements(
    cell: Cell, original_text: str, replacements: list[Replacement]
) -> None:
    """Собрать новое значение ячейки, вырезав сущности и вставив их маркеры.

    Ячейка XLSX — одна строка без run'ов, поэтому, в отличие от DOCX, здесь
    не нужно расщепление по границам форматирования: достаточно склеить
    кусочки исходного текста между заменами. Если исходная ячейка была
    формулой, результат всё равно становится обычной строкой — формула не
    сохраняется (см. докстринг модуля, «главный риск»).
    """
    ordered = sorted(replacements, key=lambda r: r.entity.start)
    pieces: list[str] = []
    cursor = 0
    for replacement in ordered:
        start = max(cursor, replacement.entity.start)
        end = max(start, replacement.entity.end)
        if start >= len(original_text) and cursor >= len(original_text):
            continue
        pieces.append(original_text[cursor:start])
        pieces.append(replacement.marker)
        cursor = end
    pieces.append(original_text[cursor:])
    cell.value = "".join(pieces)


def _apply_cell_style(cell: Cell, style: str) -> None:
    """Залить ячейку и перекрасить только цвет шрифта, не теряя остальное форматирование."""
    fill_color = "FFE8E8E8" if style == "marker" else "FF000000"
    font_color = "FF333333" if style == "marker" else "FF000000"
    cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")
    existing = cell.font
    cell.font = Font(
        name=existing.name,
        size=existing.size,
        bold=existing.bold,
        italic=existing.italic,
        vertAlign=existing.vertAlign,
        underline=existing.underline,
        strike=existing.strike,
        color=font_color,
    )


def render_xlsx_redacted(
    source: str | pathlib.Path,
    destination: str | pathlib.Path,
    document: Document,
    plan: MaskPlan,
    *,
    style: str = "marker",
) -> None:
    """Создать обезличенную копию XLSX: сущности заменены маркерами плана.

    style="marker"   — светло-серая заливка, маркер плана тёмным текстом.
    style="blackbox" — чёрная заливка, маркер плана чёрным текстом (визуально невидим).

    Структура книги не меняется: число листов, строк, столбцов,
    объединённых ячеек, ширины и стили остаются как в источнике —
    правятся только значения и заливка/цвет шрифта задетых ячеек.

    Кэш вычисленных значений формул чистится побочным эффектом: книга
    открывается без `data_only` (значение формульной ячейки — код, а не
    число) и после любой правки полностью пересохраняется через
    `openpyxl`, который не переносит закэшированный `<v>` формулы в новый
    файл (проверено эмпирически на файле с вручную внедрённым кэшем —
    после раунда «открыть без `data_only` → сохранить» кэш пуст для всех
    формул книги, не только для тронутых). Отдельно, до общей пересборки,
    обезвреживаются формулы, зависящие от замаскированных ячеек
    (`_neutralize_dependent_formulas`) — иначе кэш просто запишется заново
    при следующем открытии в Excel и раскроет то же значение снова.

    Сводные таблицы книги — причина немедленного отказа
    (`XlsxPivotTableError`), не частичного маскирования: см. докстринг
    `XlsxPivotTableError`.
    """
    if style not in ("marker", "blackbox"):
        raise ValueError(f"неизвестный стиль редактирования: {style!r}")

    source = pathlib.Path(source)
    destination = pathlib.Path(destination)
    shutil.copy2(source, destination)
    workbook = load_workbook(str(destination))
    _reject_pivot_tables(workbook)

    segments_by_locator = {
        cast(XlsxLocator, segment.anchor.locator): segment for segment in document.segments
    }

    by_locator: dict[XlsxLocator, list[Replacement]] = defaultdict(list)
    for replacement in plan.replacements:
        locator = cast(XlsxLocator, replacement.anchor.locator)
        by_locator[locator].append(replacement)

    masked: set[CellCoord] = set()
    for locator, cell_replacements in by_locator.items():
        cell = resolve_anchor(workbook, locator)
        segment = segments_by_locator.get(locator)
        if cell is None or segment is None:
            continue
        _apply_cell_replacements(cell, segment.text, cell_replacements)
        _apply_cell_style(cell, style)
        _, sheet_name, row, col = locator
        assert isinstance(sheet_name, str)
        assert isinstance(row, int)
        assert isinstance(col, int)
        masked.add((sheet_name, row, col))

    converted = _neutralize_dependent_formulas(workbook, masked)
    for sheet_name, row, col in converted:
        _apply_cell_style(workbook[sheet_name].cell(row=row, column=col), style)

    props = workbook.properties
    for attr in (
        "creator",
        "lastModifiedBy",
        "title",
        "subject",
        "keywords",
        "description",
        "category",
    ):
        setattr(props, attr, None)

    workbook.save(str(destination))
    os.chmod(destination, 0o600)
