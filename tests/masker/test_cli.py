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
from masker.model import CRITICAL_TYPES

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
    assert report["report_version"] == 3
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
    assert "address" not in report["detection_coverage"]["requested_without_detector"]
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


def test_cli_records_profile_and_judge_with_fake_llm(tmp_path: Path) -> None:
    config = tmp_path / "llm.yaml"
    config.write_text("llm:\n  provider: fake\n", encoding="utf-8")

    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path / "output"),
                "--rules-only",
                "--profile",
                "--llm-config",
                str(config),
            ]
        )
        == 0
    )

    report = json.loads(
        (tmp_path / "output" / FIXTURE.stem / "report.json").read_text(encoding="utf-8")
    )
    assert report["profile_judge"]["llm_calls"] == 1
    assert len(report["profile_judge"]["profiles"]) == 1
    assert len(report["profile_judge"]["verdicts"]) == report["entity_count"]


def test_cli_llm_trace_requires_profile(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main([str(FIXTURE), "--out", str(tmp_path), "--rules-only", "--llm-trace"])


def test_cli_llm_trace_writes_readable_and_machine_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "llm.yaml"
    config.write_text("llm:\n  provider: fake\n", encoding="utf-8")

    exit_code = main(
        [
            str(FIXTURE),
            "--out",
            str(tmp_path / "output"),
            "--rules-only",
            "--profile",
            "--llm-config",
            str(config),
            "--llm-trace",
        ]
    )

    assert exit_code == 0
    artifact_dir = tmp_path / "output" / FIXTURE.stem
    jsonl_path = artifact_dir / "llm-trace.jsonl"
    markdown_path = artifact_dir / "llm-trace.md"
    assert jsonl_path.is_file()
    assert markdown_path.is_file()
    assert stat.S_IMODE(jsonl_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(markdown_path.stat().st_mode) == 0o600

    lines = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["kind"] == "call" for record in lines)

    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Трейс обмена с LLM" in markdown
    assert "### Ответ модели (дословно)" in markdown

    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert any("llm-trace" in item for item in report["limitations"])

    captured = capsys.readouterr()
    assert "llm-trace.jsonl" in captured.out
    assert "исходные PII в открытом виде" in captured.out


def test_cli_llm_trace_without_llm_config_is_a_noop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [str(FIXTURE), "--out", str(tmp_path), "--rules-only", "--profile", "--llm-trace"]
    )

    assert exit_code == 0
    artifact_dir = tmp_path / FIXTURE.stem
    assert not (artifact_dir / "llm-trace.jsonl").exists()
    assert not (artifact_dir / "llm-trace.md").exists()
    captured = capsys.readouterr()
    assert "LLM не подключена" in captured.out


def test_cli_requires_explicit_consent_for_remote_pii(tmp_path: Path) -> None:
    config = tmp_path / "llm.yaml"
    config.write_text("llm:\n  provider: openrouter\n  model: openrouter/auto\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main([str(FIXTURE), "--profile", "--llm-config", str(config)])


@pytest.mark.parametrize("rules_only", [False, True])
def test_detection_coverage_follows_detector_set(tmp_path: Path, rules_only: bool) -> None:
    args = [str(FIXTURE), "--out", str(tmp_path), "--types", "all"]
    if rules_only:
        args.append("--rules-only")

    assert main(args) == 0

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["detection_coverage"]["requested_without_detector"] == [
        "bank_name",
        "contract_number",
        "date",
        "money",
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


FIXTURE_HUMAN = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def _ask_contract_01(tmp_path: Path, extra: list[str] | None = None) -> dict:
    args = [str(FIXTURE_HUMAN), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"]
    args.extend(extra or [])
    assert main(args) == 10
    return json.loads((tmp_path / "contract_01" / "questions.json").read_text(encoding="utf-8"))


def _write_answers(tmp_path: Path, thread_id: str, answers: dict[str, str]) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(
        json.dumps({"schema_version": 1, "thread_id": thread_id, "answers": answers}),
        encoding="utf-8",
    )
    return path


def test_decisions_block_reflects_type_keep_and_preview_excludes_it(tmp_path: Path) -> None:
    """Групповой ответ на TYPE-* доходит до отчёта и preview, когда он и

    побеждает по приоритету. В contract_01.docx каждая сущность структурно
    кластеризуется в профиль (Поставщик/Покупатель) — ``PolicyAgent.apply``
    уже проверен на «голом» TYPE-победе без профиля юнит-тестом
    (``tests/masker/policy/test_apply.py::test_type_keep_answer_masks_only_that_type``);
    здесь достаточно снять оба профиля ответом «оставить», чтобы TYPE-ответ
    по некритичному типу реально долетел до keep, а критичный остался
    замаскирован гвардией.
    """
    payload = _ask_contract_01(tmp_path)
    thread_id = payload["thread_id"]
    answers = {q["id"]: q["default"] for q in payload["questions"]}
    answers["PROFILE-P1"] = "оставить"
    answers["PROFILE-P2"] = "оставить"
    answers_path = _write_answers(tmp_path, thread_id, answers)

    assert (
        main(
            [
                "--resume",
                thread_id,
                "--out",
                str(tmp_path),
                "--profile",
                "--answers",
                str(answers_path),
            ]
        )
        == 0
    )

    report_path = tmp_path / "contract_01" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["report_version"] == 3
    phone_records = [item for item in report["entities"] if item["type"] == "phone"]
    assert phone_records
    for record in phone_records:
        assert record["decision"] == "keep"
        assert record["decided_by"] == "profile"
        assert "выбор человека" in record["reason"]
    inn_records = [item for item in report["entities"] if item["type"] == "inn"]
    assert inn_records
    assert all(record["decision"] == "mask" for record in inn_records)
    assert all(record["decided_by"] == "critical_guard" for record in inn_records)

    preview = open_docx(tmp_path / "contract_01" / "preview.docx")
    highlighted = {
        run.text
        for paragraph in preview.paragraphs
        for run in iter_runs(paragraph)
        if run.font.highlight_color == WD_COLOR_INDEX.YELLOW
    }
    assert not ({record["text"] for record in phone_records} & highlighted)
    assert {record["text"] for record in inn_records} <= highlighted
    assert "interrupt" not in report_path.read_text(encoding="utf-8")


def test_decisions_block_reflects_profile_keep(tmp_path: Path) -> None:
    payload = _ask_contract_01(tmp_path)
    thread_id = payload["thread_id"]
    answers = {q["id"]: q["default"] for q in payload["questions"]}
    answers["PROFILE-P2"] = "оставить"
    answers_path = _write_answers(tmp_path, thread_id, answers)

    assert (
        main(
            [
                "--resume",
                thread_id,
                "--out",
                str(tmp_path),
                "--profile",
                "--answers",
                str(answers_path),
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / "contract_01" / "report.json").read_text(encoding="utf-8"))
    by_ref = {item["ref"]: item for item in report["decisions"]["by_ref"]}
    profiles = {item["id"]: item for item in report["profile_judge"]["profiles"]}
    critical_type_values = {entity_type.value for entity_type in CRITICAL_TYPES}
    p2_non_critical_refs = {
        member["ref"]
        for member in profiles["P2"]["members"]
        if member["entity"]["type"] not in critical_type_values
    }
    p2_critical_refs = {
        member["ref"]
        for member in profiles["P2"]["members"]
        if member["entity"]["type"] in critical_type_values
    }
    assert p2_non_critical_refs
    for ref in p2_non_critical_refs:
        assert by_ref[ref]["action"] == "keep"
    # Критичные реквизиты того же профиля без --unmask-critical всё равно
    # замаскированы гвардией — обычное «оставить» не снимает их.
    for ref in p2_critical_refs:
        assert by_ref[ref]["action"] == "mask"
        assert by_ref[ref]["decided_by"] == "critical_guard"
    other_refs = {
        member["ref"]
        for profile_id, profile in profiles.items()
        if profile_id != "P2"
        for member in profile["members"]
    }
    assert other_refs
    assert any(by_ref[ref]["action"] == "mask" for ref in other_refs)


def test_critical_unmask_shows_banner_and_limitation(tmp_path: Path) -> None:
    """Двойное подтверждение снимает маску с критичного типа.

    Раз каждая критичная сущность в contract_01.docx состоит в профиле,
    а профиль по приоритету частнее типа (раздел 4 плана T1.5.1), для
    реального снятия маски осознанный ответ нужен и на PROFILE-*, не только
    на TYPE-inn — иначе профильный default («маскировать») победит.
    """
    payload = _ask_contract_01(tmp_path, extra=["--unmask-critical"])
    thread_id = payload["thread_id"]
    inn_question = next(q for q in payload["questions"] if q["id"] == "TYPE-inn")
    assert "оставить (осознанное решение)" in inn_question["options"]
    answers = {q["id"]: q["default"] for q in payload["questions"]}
    answers["TYPE-inn"] = "оставить (осознанное решение)"
    answers["PROFILE-P1"] = "оставить (осознанное решение)"
    answers["PROFILE-P2"] = "оставить (осознанное решение)"
    answers_path = _write_answers(tmp_path, thread_id, answers)

    assert (
        main(
            [
                "--resume",
                thread_id,
                "--out",
                str(tmp_path),
                "--profile",
                "--answers",
                str(answers_path),
                "--html",
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / "contract_01" / "report.json").read_text(encoding="utf-8"))
    assert report["decisions"]["critical_unmasked"]
    assert any("осознанн" in item.casefold() for item in report["limitations"])
    html = (tmp_path / "contract_01" / "report.html").read_text(encoding="utf-8")
    assert "критич" in html.casefold()


# ── PDF ───────────────────────────────────────────────────────────────────────


def _make_pdf_with_inn(path: Path) -> None:
    import pymupdf

    font = str(ROOT / "src" / "masker" / "data" / "DejaVuSans.ttf")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_font(fontname="dvu", fontfile=font)
    page.insert_text((72, 100), "ИНН 3662103003", fontname="dvu", fontsize=12)
    doc.save(str(path))
    doc.close()


def test_cli_accepts_pdf_file(tmp_path: Path) -> None:
    src = tmp_path / "contract.pdf"
    _make_pdf_with_inn(src)
    assert main([str(src), "--out", str(tmp_path / "out"), "--rules-only"]) == 0


def test_cli_pdf_creates_report_and_preview(tmp_path: Path) -> None:
    src = tmp_path / "contract.pdf"
    _make_pdf_with_inn(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only"])
    artifact_dir = tmp_path / "out" / "contract"
    assert (artifact_dir / "report.json").exists()
    assert (artifact_dir / "preview.pdf").exists()


def test_cli_pdf_report_format_field(tmp_path: Path) -> None:
    src = tmp_path / "contract.pdf"
    _make_pdf_with_inn(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only"])
    report = json.loads((tmp_path / "out" / "contract" / "report.json").read_text(encoding="utf-8"))
    assert report["format"] == "pdf"
    assert report["entity_count"] >= 1


def test_cli_pdf_artifacts_permissions(tmp_path: Path) -> None:
    src = tmp_path / "contract.pdf"
    _make_pdf_with_inn(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only"])
    artifact_dir = tmp_path / "out" / "contract"
    assert stat.S_IMODE((artifact_dir / "report.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((artifact_dir / "preview.pdf").stat().st_mode) == 0o600


# ── DOCX redact ───────────────────────────────────────────────────────────────


def _make_simple_docx(path: Path) -> None:
    doc = open_docx()
    doc.core_properties.author = "Тест Автор"
    doc.add_paragraph("ИНН 3662103003")
    doc.save(str(path))


def test_cli_docx_redact_creates_file(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    assert (
        main([str(src), "--out", str(tmp_path / "out"), "--rules-only", "--redact-style", "marker"])
        == 0
    )
    assert (tmp_path / "out" / "contract" / "redacted.docx").exists()


def test_cli_docx_redact_permissions(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only", "--redact-style", "marker"])
    redacted = tmp_path / "out" / "contract" / "redacted.docx"
    assert stat.S_IMODE(redacted.stat().st_mode) == 0o600


def test_cli_docx_no_redact_without_flag(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only"])
    assert not (tmp_path / "out" / "contract" / "redacted.docx").exists()


def test_cli_docx_report_preview_only_false(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only", "--redact-style", "blackbox"])
    report = json.loads((tmp_path / "out" / "contract" / "report.json").read_text(encoding="utf-8"))
    assert report["preview_only"] is False


def test_cli_still_rejects_txt(tmp_path: Path) -> None:
    source = tmp_path / "contract.txt"
    source.write_text("test", encoding="utf-8")
    with pytest.raises(SystemExit, match="2"):
        main([str(source), "--out", str(tmp_path)])
