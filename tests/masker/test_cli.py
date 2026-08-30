from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from docx import Document as open_docx
from docx.enum.text import WD_COLOR_INDEX

from masker.cli import main
from masker.ingest.docx_ingest import iter_runs

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_02_hard.docx"
TABLE_FIXTURE = ROOT / "fixtures" / "labeled" / "contract_05_tables.docx"


def table_shape(path: Path) -> list[tuple[int, list[int], int]]:
    source = open_docx(path)
    result: list[tuple[int, list[int], int]] = []
    for table in source.tables:
        grid = table._tbl.tblGrid
        result.append(
            (
                len(table._tbl.tr_lst),
                [len(row.tc_lst) for row in table._tbl.tr_lst],
                len(grid.gridCol_lst) if grid is not None else 0,
            )
        )
    return result


def test_cli_creates_report_and_exact_preview(tmp_path: Path) -> None:
    source_hash = hashlib.sha256(FIXTURE.read_bytes()).digest()

    assert main([str(FIXTURE), "--out", str(tmp_path), "--rules-only", "--html"]) == 0

    artifact_dir = tmp_path / FIXTURE.stem
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    preview = open_docx(artifact_dir / "preview.docx")
    html = (artifact_dir / "report.html").read_text(encoding="utf-8")
    original = open_docx(FIXTURE)

    assert report["preview_only"] is True
    assert report["report_version"] == 2
    assert report["entity_count"] == 4
    assert report["chunk_count"] == 3
    assert {item["type"] for item in report["entities"]} == {
        "email",
        "inn",
        "passport",
        "snils",
    }
    assert report["summary"] == {
        "entities_total": 4,
        "by_type": {"email": 1, "inn": 1, "passport": 1, "snils": 1},
        "by_source": {"rule": 4},
        "minimum_confidence": 0.9,
    }
    first_chunk = report["chunks"][0]
    assert first_chunk["pii_count"] == 2
    assert [item["type"] for item in first_chunk["pii"]] == ["inn", "snils"]
    assert "⟦INN:500100732259⟧" in first_chunk["annotated_text"]
    assert "⟦SNILS:112-233-445 95⟧" in first_chunk["annotated_text"]
    assert (
        first_chunk["text"][
            first_chunk["pii"][0]["chunk_start"] : first_chunk["pii"][0]["chunk_end"]
        ]
        == "500100732259"
    )
    assert report["document_coverage"]["tables"] == {
        "processed": True,
        "count": 0,
        "nonempty_paragraphs": 0,
        "nested_count": 0,
    }
    assert report["document_coverage"]["body"]["skipped_blocks"] == 0
    assert report["document_coverage"]["safe_to_export"] is False
    assert "address" in report["detection_coverage"]["requested_without_detector"]
    assert [paragraph.text for paragraph in preview.paragraphs] == [
        paragraph.text for paragraph in original.paragraphs
    ]
    highlighted = [
        run.text
        for paragraph in preview.paragraphs
        for run in iter_runs(paragraph)
        if run.font.highlight_color == WD_COLOR_INDEX.YELLOW
    ]
    assert "500100732259" in highlighted
    assert 'class="pii pii-inn"' in html
    assert 'id="full-document"' in html
    assert 'class="chunk-range"' in html
    assert "Накладная № 3662103004" in html
    assert "chunk-001" in html
    assert "НЕ БЕЗОПАСЕН ДЛЯ ЭКСПОРТА" in html
    assert hashlib.sha256(FIXTURE.read_bytes()).digest() == source_hash
    assert stat.S_IMODE((artifact_dir / "report.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((artifact_dir / "preview.docx").stat().st_mode) == 0o600
    assert stat.S_IMODE((artifact_dir / "report.html").stat().st_mode) == 0o600


def test_cli_filters_entity_types(tmp_path: Path) -> None:
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--types",
                "inn,snils",
                "--rules-only",
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["entity_count"] == 2
    assert [item["type"] for item in report["entities"]] == ["inn", "snils"]
    assert report["detection_coverage"]["requested_without_detector"] == []


def test_cli_uses_ner_by_default(tmp_path: Path) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--types", "person"]) == 0

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert [(item["type"], item["text"]) for item in report["entities"]] == [
        ("person", "Кузнецов Пётр Алексеевич")
    ]


def test_cli_highlights_entity_split_across_runs(tmp_path: Path) -> None:
    source_path = tmp_path / "split-runs.docx"
    output_path = tmp_path / "output"
    source = open_docx()
    paragraph = source.add_paragraph()
    for text in ("<script>ИНН ", "500100", "732259", "</script>"):
        paragraph.add_run(text)
    source.save(source_path)

    assert main([str(source_path), "--out", str(output_path), "--rules-only", "--html"]) == 0

    preview = open_docx(output_path / "split-runs" / "preview.docx")
    runs = iter_runs(preview.paragraphs[0])
    assert "".join(run.text for run in runs) == "<script>ИНН 500100732259</script>"
    assert [run.text for run in runs if run.font.highlight_color == WD_COLOR_INDEX.YELLOW] == [
        "500100",
        "732259",
    ]
    html = (output_path / "split-runs" / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_preview_highlights_entity_inside_table_cell(tmp_path: Path) -> None:
    source_path = tmp_path / "table-cell.docx"
    output_path = tmp_path / "output"
    source = open_docx()
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "ИНН 500100732259"
    source.save(source_path)

    assert main([str(source_path), "--out", str(output_path), "--rules-only", "--html"]) == 0

    preview = open_docx(output_path / "table-cell" / "preview.docx")
    highlighted = [
        run.text
        for row in preview.tables[0].rows
        for cell in row.cells
        for paragraph in cell.paragraphs
        for run in iter_runs(paragraph)
        if run.font.highlight_color == WD_COLOR_INDEX.YELLOW
    ]
    html = (output_path / "table-cell" / "report.html").read_text(encoding="utf-8")
    assert highlighted == ["500100732259"]
    assert "<span>Таблица 1</span><span>обработана</span>" in html
    assert 'class="pii pii-inn"' in html


def test_preview_keeps_table_shape(tmp_path: Path) -> None:
    assert main([str(TABLE_FIXTURE), "--out", str(tmp_path), "--rules-only"]) == 0

    assert table_shape(tmp_path / TABLE_FIXTURE.stem / "preview.docx") == table_shape(TABLE_FIXTURE)


def test_preview_highlights_entity_split_across_runs_in_cell(tmp_path: Path) -> None:
    source_path = tmp_path / "split-runs-cell.docx"
    output_path = tmp_path / "output"
    source = open_docx()
    table = source.add_table(rows=1, cols=1)
    paragraph = table.cell(0, 0).paragraphs[0]
    for text in ("<script>ИНН ", "500100", "732259", "</script>"):
        paragraph.add_run(text)
    source.save(source_path)

    assert main([str(source_path), "--out", str(output_path), "--rules-only", "--html"]) == 0

    preview = open_docx(output_path / "split-runs-cell" / "preview.docx")
    runs = iter_runs(preview.tables[0].cell(0, 0).paragraphs[0])
    assert "".join(run.text for run in runs) == "<script>ИНН 500100732259</script>"
    assert [run.text for run in runs if run.font.highlight_color == WD_COLOR_INDEX.YELLOW] == [
        "500100",
        "732259",
    ]
    html = (output_path / "split-runs-cell" / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_rejects_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main([str(FIXTURE), "--out", str(tmp_path), "--types", "unknown"])


def test_cli_rejects_non_docx(tmp_path: Path) -> None:
    source = tmp_path / "contract.txt"
    source.write_text("test", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main([str(source), "--out", str(tmp_path)])


def test_report_exposes_processed_tables_and_unprocessed_metadata(tmp_path: Path) -> None:
    source_path = tmp_path / "table.docx"
    source = open_docx()
    source.core_properties.author = "Test Author"
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "ИНН 500100732259"
    source.save(source_path)

    assert (
        main(
            [
                str(source_path),
                "--out",
                str(tmp_path / "output"),
                "--rules-only",
                "--html",
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / "output" / "table" / "report.json").read_text(encoding="utf-8"))
    assert report["entity_count"] == 1
    assert report["document_coverage"]["tables"] == {
        "processed": True,
        "count": 1,
        "nonempty_paragraphs": 1,
        "nested_count": 0,
    }
    assert report["document_coverage"]["safe_to_export"] is False
    assert "author" in report["document_coverage"]["metadata"]["present_fields"]
    assert all("Таблицы, колонтитулы" not in item for item in report["limitations"])
    html = (tmp_path / "output" / "table" / "report.html").read_text(encoding="utf-8")
    assert "НЕ ОБРАБОТАНА ДЕТЕКТОРОМ" not in html
    assert "<span>Таблица 1</span><span>обработана</span>" in html
    assert "ИНН " in html
    assert "500100732259" in html
    assert 'class="pii pii-inn"' in html
    assert "Test Author" in html


def test_safe_to_export_stays_false_until_headers_and_render(tmp_path: Path) -> None:
    assert main([str(TABLE_FIXTURE), "--out", str(tmp_path), "--rules-only"]) == 0

    report = json.loads((tmp_path / TABLE_FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["document_coverage"]["tables"]["processed"] is True
    assert report["document_coverage"]["tables"]["nested_count"] == 1
    assert report["document_coverage"]["safe_to_export"] is False
    assert any("Вложенные таблицы" in item for item in report["limitations"])
