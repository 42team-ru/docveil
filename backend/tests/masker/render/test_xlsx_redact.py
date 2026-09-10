"""Тесты xlsx_redact: настоящее редактирование XLSX через `MaskPlan`.

Главный блок — `TestFormulaDependencyLeak`: формула, ссылающаяся на
замаскированную ячейку (прямо, транзитивно, через другой лист или через
именованный диапазон), не должна отдавать исходное значение — ни как
формулу, ни как закэшированный результат вычисления (см. AGENTS.md,
«главный риск М7»). Каждый тест этого блока обязан падать на откате
`_neutralize_dependent_formulas`/`resolve_formula_references` к «ничего не
делать» — без этого модуль просто оставляет утечку формулой на месте.
"""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path
from typing import cast

import openpyxl
import pytest
from openpyxl.workbook.defined_name import DefinedName

from masker.ingest.xlsx_ingest import ingest_xlsx
from masker.mask.agent import PlanAgent
from masker.model import Document, Entity, EntityType, MaskPlan, Source
from masker.render.xlsx_redact import (
    FORMULA_MARKER,
    XlsxPivotTableError,
    render_xlsx_redacted,
)

_INN = "3662103003"


def _entity(
    document: Document, text: str, etype: EntityType, *, cell_text: str | None = None
) -> Entity:
    """Построить `Entity` для сущности, найденной в тексте конкретной ячейки.

    `cell_text` нужен, когда несколько сегментов совпадают по `text` целиком
    (не в этом файле, но на будущее) — по умолчанию ищем сегмент, чей текст
    равен `text`.
    """
    target = cell_text if cell_text is not None else text
    seg = next(s for s in document.segments if s.text == target)
    start = seg.text.index(text)
    return Entity(
        type=etype,
        text=text,
        segment_order=seg.order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=text,
    )


def _plan(document: Document, entities: list[Entity]) -> MaskPlan:
    return PlanAgent().plan(document, entities)


def _make_workbook(path: Path, cells: dict[tuple[str, str], object]) -> None:
    """Собрать книгу из словаря `(лист, координата) -> значение`."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    sheets: dict[str, object] = {}
    for (sheet_name, coordinate), value in cells.items():
        sheet = sheets.get(sheet_name)
        if sheet is None:
            sheet = workbook.create_sheet(sheet_name)
            sheets[sheet_name] = sheet
        sheet[coordinate] = value
    workbook.save(path)


def _load_all_text(path: Path) -> str:
    """Текст частей архива xlsx, где вообще может лежать содержимое ячеек.

    Не весь архив: `xl/theme/*.xml` — тема оформления, там встречаются
    произвольные числа (id темы, ревизия) и это не место для данных
    пользователя. Проверка утечки по всему архиву проверяла бы то, что не
    относится к данным, и ловила бы случайные числовые совпадения в теме.
    """
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.startswith("xl/worksheets/")
            or name in ("xl/sharedStrings.xml", "xl/calcChain.xml")
        ]
        return "\n".join(archive.read(name).decode("utf-8", errors="ignore") for name in names)


class TestFormulaDependencyLeak:
    """Критерий приёмки 2 плана М7: `leaked_total = 0` по формулам."""

    def test_direct_reference_is_neutralized(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "A1"): "ИНН",
                ("Sheet1", "B1"): _INN,
                ("Sheet1", "D7"): "=B1",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        assert _INN not in _load_all_text(destination)
        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["D7"].value == FORMULA_MARKER
        assert result["Sheet1"]["D7"].data_type != "f"
        cached = openpyxl.load_workbook(destination, data_only=True)
        assert cached["Sheet1"]["D7"].value != _INN

    def test_arithmetic_formula_does_not_recompute_masked_value(self, tmp_path: Path) -> None:
        """Ровно сценарий из докстринга модуля: `B2` — сумма, `D7 = B2*1.2`."""
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "A2"): "Сумма договора",
                ("Sheet1", "B2"): 1_000_000,
                ("Sheet1", "D7"): "=B2*1.2",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, "1000000", EntityType.MONEY)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["D7"].value == FORMULA_MARKER
        assert "1000000" not in _load_all_text(destination)
        assert "1200000" not in _load_all_text(destination)

    def test_reference_survives_without_masking_when_source_untouched(self, tmp_path: Path) -> None:
        """Контрольный случай: формула, не зависящая от маски, остаётся формулой."""
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "A1"): "ИНН",
                ("Sheet1", "B1"): _INN,
                ("Sheet1", "C1"): 10,
                ("Sheet1", "D1"): "=C1*2",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["D1"].value == "=C1*2"
        assert result["Sheet1"]["D1"].data_type == "f"

    def test_cross_sheet_reference_is_neutralized(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Реестр", "B1"): _INN,
                ("Свод", "B1"): "=Реестр!B1",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        assert _INN not in _load_all_text(destination)
        result = openpyxl.load_workbook(destination)
        assert result["Свод"]["B1"].value == FORMULA_MARKER

    def test_range_reference_is_neutralized(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "B2"): 500_000,
                ("Sheet1", "B3"): 500_000,
                ("Sheet1", "B10"): "=SUM(B1:B5)",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, "500000", EntityType.MONEY, cell_text="500000")
        # Первый сегмент с текстом "500000" — B2; замаскируем именно его.
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["B10"].value == FORMULA_MARKER

    def test_named_range_reference_is_neutralized(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "B1"): _INN,
                ("Sheet1", "D1"): "=ИННПоставщика",
            },
        )
        workbook = openpyxl.load_workbook(source)
        workbook.defined_names["ИННПоставщика"] = DefinedName(
            "ИННПоставщика", attr_text="Sheet1!$B$1"
        )
        workbook.save(source)

        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        assert _INN not in _load_all_text(destination)
        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["D1"].value == FORMULA_MARKER

    def test_transitive_chain_is_neutralized(self, tmp_path: Path) -> None:
        """`E5 = D7 + 5`, `D7 = B2 * 1.2`, `B2` замаскирован — обе формулы обезврежены."""
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "B2"): 1_000_000,
                ("Sheet1", "D7"): "=B2*1.2",
                ("Sheet1", "E5"): "=D7+5",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, "1000000", EntityType.MONEY)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["D7"].value == FORMULA_MARKER
        assert result["Sheet1"]["E5"].value == FORMULA_MARKER

    def test_cached_formula_value_is_wiped_even_when_untouched(self, tmp_path: Path) -> None:
        """Кэш формулы, ничего не масковавшей и ни от чего не зависящей,
        всё равно очищается побочным эффектом пересохранения через
        `openpyxl` (см. докстринг `render_xlsx_redacted`)."""
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "A1"): "ИНН",
                ("Sheet1", "B1"): _INN,
                ("Sheet1", "C1"): 10,
                ("Sheet1", "D1"): "=C1*2",
            },
        )
        _bake_cached_value(source, "Sheet1", "D1", "20")

        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        cached = openpyxl.load_workbook(destination, data_only=True)
        assert cached["Sheet1"]["D1"].value is None


class TestPivotTableGuard:
    def test_pivot_table_raises_instead_of_silently_masking(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        monkeypatch.setattr("masker.render.xlsx_redact._has_pivot_tables", lambda workbook: True)

        destination = tmp_path / "out.xlsx"
        with pytest.raises(XlsxPivotTableError):
            render_xlsx_redacted(source, destination, document, plan)


class TestDirectReplacement:
    def test_marker_replaces_cell_value(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])
        marker = plan.replacements[0].marker

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        assert result["Sheet1"]["B1"].value == marker
        assert _INN not in _load_all_text(destination)

    def test_multiple_entities_in_one_cell_are_spliced(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        kpp = "366201001"
        cell_text = f"ИНН {_INN}, КПП {kpp}"
        _make_workbook(source, {("Sheet1", "B1"): cell_text})
        document = ingest_xlsx(source)
        inn_entity = _entity(document, _INN, EntityType.INN, cell_text=cell_text)
        kpp_entity = _entity(document, kpp, EntityType.KPP, cell_text=cell_text)
        plan = _plan(document, [inn_entity, kpp_entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        result = openpyxl.load_workbook(destination)
        value = cast(str, result["Sheet1"]["B1"].value)
        assert _INN not in value
        assert kpp not in value
        assert "ИНН" in value
        assert "КПП" in value
        assert _INN not in _load_all_text(destination)
        assert kpp not in _load_all_text(destination)

    def test_blackbox_style_and_marker_style_both_remove_source_text(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        for style in ("marker", "blackbox"):
            destination = tmp_path / f"out-{style}.xlsx"
            render_xlsx_redacted(source, destination, document, plan, style=style)
            assert _INN not in _load_all_text(destination)

    def test_unknown_style_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        with pytest.raises(ValueError, match="неизвестный стиль"):
            render_xlsx_redacted(source, tmp_path / "out.xlsx", document, plan, style="rainbow")

    def test_destination_is_owner_only_readable(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        mode = stat.S_IMODE(destination.stat().st_mode)
        assert mode == 0o600


class TestStructurePreserved:
    def test_sheets_rows_columns_and_merges_are_unchanged(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Реестр"
        sheet.merge_cells("A1:B1")
        sheet["A1"] = "Заголовок"
        sheet["A2"] = "ИНН"
        sheet["B2"] = _INN
        sheet.column_dimensions["A"].width = 22
        workbook.create_sheet("Свод")
        workbook.save(source)

        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        destination = tmp_path / "out.xlsx"
        render_xlsx_redacted(source, destination, document, plan)

        before = openpyxl.load_workbook(source)
        after = openpyxl.load_workbook(destination)

        assert after.sheetnames == before.sheetnames
        for name in before.sheetnames:
            before_sheet = before[name]
            after_sheet = after[name]
            assert after_sheet.dimensions == before_sheet.dimensions
            assert after_sheet.merged_cells.ranges == before_sheet.merged_cells.ranges
        assert after["Реестр"].column_dimensions["A"].width == 22

    def test_source_file_is_not_modified(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(source, {("Sheet1", "B1"): _INN})
        before = source.read_bytes()

        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])
        render_xlsx_redacted(source, tmp_path / "out.xlsx", document, plan)

        assert source.read_bytes() == before


class TestIdempotency:
    def test_second_pass_over_masked_file_changes_nothing(self, tmp_path: Path) -> None:
        source = tmp_path / "source.xlsx"
        _make_workbook(
            source,
            {
                ("Sheet1", "A1"): "ИНН",
                ("Sheet1", "B1"): _INN,
                ("Sheet1", "D7"): "=B1",
            },
        )
        document = ingest_xlsx(source)
        entity = _entity(document, _INN, EntityType.INN)
        plan = _plan(document, [entity])

        first = tmp_path / "first.xlsx"
        render_xlsx_redacted(source, first, document, plan)

        from masker.detect.agent import DetectAgent

        document2 = ingest_xlsx(first)
        plan2 = _plan(document2, DetectAgent().detect(document2).entities)
        second = tmp_path / "second.xlsx"
        render_xlsx_redacted(first, second, document2, plan2)

        assert plan2.replacements == ()

        first_snapshot = _content_snapshot(first)
        second_snapshot = _content_snapshot(second)
        assert first_snapshot == second_snapshot


def _content_snapshot(path: Path) -> dict[tuple[str, int, int], object]:
    workbook = openpyxl.load_workbook(path)
    snapshot: dict[tuple[str, int, int], object] = {}
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is not None:
                    snapshot[(sheet.title, cell.row, cell.column)] = cell.value
    return snapshot


def _bake_cached_value(path: Path, sheet_name: str, coordinate: str, cached: str) -> None:
    """Вписать в готовый xlsx кэш вычисления формулы напрямую в XML.

    Ровно тот же приём, что и в `tests/masker/ingest/test_xlsx_ingest.py`:
    `openpyxl` не пишет кэш формул сам, и тесту, которому нужен файл с уже
    существующим кэшем (как у настоящей книги, открытой в Excel), приходится
    вписать его в обход `openpyxl`. Продуктовый код так не делает нигде.
    """
    import re

    sheet_index = openpyxl.load_workbook(path).sheetnames.index(sheet_name) + 1
    member = f"xl/worksheets/sheet{sheet_index}.xml"
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}

    xml = contents[member].decode("utf-8")
    pattern = re.compile(rf'(<c r="{coordinate}"[^>]*>.*?<f>[^<]*</f>)(<v>[^<]*</v>)?(</c>)')
    xml = pattern.sub(rf"\g<1><v>{cached}</v>\g<3>", xml, count=1)
    contents[member] = xml.encode("utf-8")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(name, contents[name])
