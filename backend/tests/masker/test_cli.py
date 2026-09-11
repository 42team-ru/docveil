from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
from pathlib import Path

import pytest
from docx import Document as open_docx
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn

import masker.render.docx_redact as docx_redact_module
from masker.cli import EXIT_LEAK, main
from masker.cli_ui import CliPresenter, ensure_utf8_output
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

    assert main([str(FIXTURE), "--out", str(tmp_path), "--rules-only"]) == 0

    artifact_dir = tmp_path / FIXTURE.stem
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    preview = open_docx(artifact_dir / "preview.docx")
    original = open_docx(FIXTURE)

    assert report["preview_only"] is True
    assert report["report_version"] == 4
    # 4 → 6 после T1.15: две даты в фикстуре (12.02.2026, 10.05.2018).
    assert report["entity_count"] == 6
    # chunk_count тоже растёт: даты в отдельных абзацах — новые PII-чанки.
    assert report["chunk_count"] == 4
    assert {item["type"] for item in report["entities"]} == {
        "email",
        "inn",
        "passport",
        "snils",
        "date",
    }
    assert report["summary"] == {
        "entities_total": 6,
        "by_type": {"email": 1, "inn": 1, "passport": 1, "snils": 1, "date": 2},
        "by_source": {"rule": 6},
        # Р8: критичные (inn/passport/snils) — confirmed; email и обе даты —
        # один сигнал правила без контрольной суммы — probable.
        "by_level": {"confirmed": 3, "probable": 3},
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
    assert hashlib.sha256(FIXTURE.read_bytes()).digest() == source_hash
    assert stat.S_IMODE((artifact_dir / "report.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((artifact_dir / "preview.docx").stat().st_mode) == 0o600
    assert not (artifact_dir / "report.html").exists()


def test_report_lists_marker_for_every_masked_entity(tmp_path: Path) -> None:
    """T1.6, шаг 6, приёмка из плана дословно: у каждой сущности, которая
    реально уходит в план (не в ``skipped``), непустой маркер, начинающийся
    с ``[``.

    ``--types all`` без ``--profile`` и без явных решений (``actions=None``
    в ``PlanAgent``) означает «маскировать всё найденное»: у этой фикстуры
    ничего не должно попасть в ``plan.skipped`` — что и проверяется явно,
    а не молчаливым допущением."""
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--types",
                "all",
                "--redact-style",
                "marker",
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["plan"]["skipped"]["count"] == 0
    assert report["entities"]
    for record in report["entities"]:
        assert record["marker"].startswith("[")
        assert record["group_id"]


def test_cli_returns_4_on_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """T1.8, шаг 10: сломанный рендер (пропущена одна замена) даёт код 4,
    в report.json ``leaked`` непуст."""
    original_redact_paragraph = docx_redact_module._redact_paragraph

    def broken(
        paragraph: object,
        replacements: list[object],
        style: str,
        highlight_background: str | None,
    ) -> None:
        original_redact_paragraph(  # type: ignore[arg-type]
            paragraph, replacements[:-1], style, highlight_background
        )

    monkeypatch.setattr(docx_redact_module, "_redact_paragraph", broken)

    rc = main(
        [
            str(FIXTURE),
            "--out",
            str(tmp_path),
            "--types",
            "all",
            "--redact-style",
            "marker",
        ]
    )

    assert rc == EXIT_LEAK
    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["leaked"]
    assert report["validation"]["ok"] is False


def test_cli_returns_0_when_clean(tmp_path: Path) -> None:
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--types",
                "all",
                "--redact-style",
                "marker",
            ]
        )
        == 0
    )
    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["leaked"] == []
    assert report["validation"]["ok"] is True
    assert report["validation"]["status"] == "checked"


def test_cli_passes_highlight_background_into_graph(tmp_path: Path) -> None:
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--rules-only",
                "--redact-style",
                "marker",
                "--highlight-background",
                "12ab34",
            ]
        )
        == 0
    )
    rendered = open_docx(tmp_path / FIXTURE.stem / "masked_highlight.docx")
    marker_run = next(
        run
        for paragraph in rendered.paragraphs
        for run in iter_runs(paragraph)
        if run.text.startswith("[")
    )
    shading = marker_run._r.find(f"{qn('w:rPr')}/{qn('w:shd')}")
    assert shading is not None
    assert shading.get(qn("w:fill")) == "12AB34"


def test_cli_without_redact_style_reports_validation_skipped(tmp_path: Path) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--types", "all"]) == 0
    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    assert report["validation"]["status"] == "skipped"
    assert report["validation"]["reason"]
    assert report["leaked"] == []


def test_cli_rejects_invalid_highlight_background(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main([str(FIXTURE), "--highlight-background", "chartreuse"])
    assert error.value.code == 2
    assert "некорректный фон подсветки" in capsys.readouterr().err


def test_cli_filters_entity_types(tmp_path: Path) -> None:
    """Фильтр по ``--types`` больше не режет детекцию (T1.6, шаг 6): в
    ``report.json`` остаются все найденные сущности, а незапрошенные типы
    осознанно уходят в ``plan.skipped`` — это то, на чём стоит Validate
    (T1.8): утечку незапрошенного типа есть чем поймать, потому что он не
    исчез из отчёта раньше времени."""
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
    # Детекция rules-only находит все типы с контрольной суммой/regex/regex+date —
    # inn, snils, passport, email, date (T1.15); person доступен только через NER.
    assert report["entity_count"] == 6
    entities_by_type = {item["type"]: item for item in report["entities"]}
    assert set(entities_by_type) == {"inn", "snils", "passport", "email", "date"}
    # Запрошенные типы дошли до плана и получили маркер.
    assert entities_by_type["inn"]["marker"] == "[ИНН]"
    assert entities_by_type["snils"]["marker"] == "[СНИЛС]"
    # Незапрошенные типы остались в отчёте, но не в плане: пустой маркер,
    # причина — фильтр по типу, а не исчезновение из детекции.
    assert entities_by_type["passport"]["marker"] == ""
    assert entities_by_type["email"]["marker"] == ""
    assert report["plan"]["requested_types"] == ["inn", "snils"]
    # После T1.15: 4 сущности незапрошенных типов (passport, email, 2×date).
    assert report["plan"]["skipped"] == {"count": 4, "by_reason": {"type_not_requested": 4}}
    assert report["detection_coverage"]["requested_without_detector"] == []


def test_detection_is_not_filtered_by_types_anymore(tmp_path: Path) -> None:
    """T1.6, шаг 6, приёмка из плана дословно: при ``--types inn``
    ``entity_count`` включает найденные ``person``, а ``plan.skipped``
    содержит их с причиной ``type_not_requested``."""
    assert main([str(FIXTURE), "--out", str(tmp_path), "--types", "inn"]) == 0

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    types_found = {item["type"] for item in report["entities"]}
    assert "person" in types_found
    person_records = [item for item in report["entities"] if item["type"] == "person"]
    assert person_records
    assert all(item["marker"] == "" for item in person_records)
    assert report["plan"]["skipped"]["by_reason"].get("type_not_requested", 0) >= len(
        person_records
    )


def test_cli_uses_ner_by_default(tmp_path: Path) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--types", "person"]) == 0

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    # Детекция больше не режется по --types: report.json видит все метки
    # фикстуры (person + inn/snils/passport/email, +date после T1.15),
    # но маркер в плане получает только запрошенный person.
    entities_by_type = {item["type"]: item for item in report["entities"]}
    assert set(entities_by_type) == {"person", "inn", "snils", "passport", "email", "date"}
    assert entities_by_type["person"]["text"] == "Кузнецов Пётр Алексеевич"
    assert entities_by_type["person"]["marker"] == "[ФИО]"
    for other in ("inn", "snils", "passport", "email", "date"):
        assert entities_by_type[other]["marker"] == ""
    assert report["plan"]["skipped"]["by_reason"] == {"type_not_requested": 6}


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
    """`contract_number` ушёл из списка (план T2.2.1, шаг 10, Д6): тип
    объявлен, доезжает до отчёта и теперь детектируется — `detect/rules.py`."""
    args = [str(FIXTURE), "--out", str(tmp_path), "--types", "all"]
    if rules_only:
        args.append("--rules-only")

    assert main(args) == 0

    report = json.loads((tmp_path / FIXTURE.stem / "report.json").read_text(encoding="utf-8"))
    # После T1.15 `date`/`birth_date` перешли в активные детекторы.
    # Фаза 1-2: contract_amount/delivery_period/payment_terms покрыты.
    # 11.09.2026 в Р20 появился детектор денежных сумм, и `money` ушёл из
    # списка непокрытых: до этого суммы не маскировались вовсе. Остался
    # только `bank_name` — название банка ищет NER, а не правило.
    # `money` покрыт детектором из Р20, но тот живёт не в слое правил:
    # в режиме `--rules-only` суммы снова остаются без детектора, и отчёт
    # обязан говорить об этом честно, а не показывать одинаковый список
    # для двух разных наборов детекторов.
    expected = ["bank_name", "money"] if rules_only else ["bank_name"]
    assert report["detection_coverage"]["requested_without_detector"] == expected


def test_cli_highlights_entity_split_across_runs(tmp_path: Path) -> None:
    source_path = tmp_path / "split-runs.docx"
    output_path = tmp_path / "output"
    source = open_docx()
    paragraph = source.add_paragraph()
    for text in ("<script>ИНН ", "500100", "732259", "</script>"):
        paragraph.add_run(text)
    source.save(source_path)

    assert main([str(source_path), "--out", str(output_path), "--rules-only"]) == 0

    preview = open_docx(output_path / "split-runs" / "preview.docx")
    runs = iter_runs(preview.paragraphs[0])
    assert "".join(run.text for run in runs) == "<script>ИНН 500100732259</script>"
    assert [run.text for run in runs if run.font.highlight_color == WD_COLOR_INDEX.YELLOW] == [
        "500100",
        "732259",
    ]


def test_preview_highlights_entity_inside_table_cell(tmp_path: Path) -> None:
    source_path = tmp_path / "table-cell.docx"
    output_path = tmp_path / "output"
    source = open_docx()
    table = source.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "ИНН 500100732259"
    source.save(source_path)

    assert main([str(source_path), "--out", str(output_path), "--rules-only"]) == 0

    preview = open_docx(output_path / "table-cell" / "preview.docx")
    highlighted = [
        run.text
        for row in preview.tables[0].rows
        for cell in row.cells
        for paragraph in cell.paragraphs
        for run in iter_runs(paragraph)
        if run.font.highlight_color == WD_COLOR_INDEX.YELLOW
    ]
    assert highlighted == ["500100732259"]


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

    assert main([str(source_path), "--out", str(output_path), "--rules-only"]) == 0

    preview = open_docx(output_path / "split-runs-cell" / "preview.docx")
    runs = iter_runs(preview.tables[0].cell(0, 0).paragraphs[0])
    assert "".join(run.text for run in runs) == "<script>ИНН 500100732259</script>"
    assert [run.text for run in runs if run.font.highlight_color == WD_COLOR_INDEX.YELLOW] == [
        "500100",
        "732259",
    ]


def test_cli_rejects_unknown_type(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main([str(FIXTURE), "--out", str(tmp_path), "--types", "unknown"])


def test_cli_rejects_non_docx(tmp_path: Path) -> None:
    source = tmp_path / "contract.txt"
    source.write_text("test", encoding="utf-8")

    with pytest.raises(SystemExit, match="2"):
        main([str(source), "--out", str(tmp_path)])


def test_cli_dry_run_describes_operation_without_writing_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "output"

    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(output),
                "--types",
                "inn,passport",
                "--dry-run",
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert "предпросмотр" in captured.out
    assert "файлы не будут записаны" in captured.out
    assert not output.exists()


def test_cli_non_tty_progress_is_plain_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--rules-only"]) == 0

    captured = capsys.readouterr()
    assert "1/10: Извлечение текста" in captured.out
    assert "10/10: Сборка отчёта" in captured.out
    assert "\x1b" not in captured.out


def test_cli_tty_progress_is_started_and_cleared(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("masker.cli_ui.sys.stdout.isatty", lambda: True)
    presenter = CliPresenter(quiet=False, verbose=False)

    presenter.begin(FIXTURE)
    assert presenter._progress is not None
    presenter.observe("extract", "started")
    presenter.observe("extract", "completed", "разобран DOCX")
    assert presenter.finish_progress() >= 0
    assert presenter._progress is None
    capsys.readouterr()


def test_cli_quiet_suppresses_regular_dry_run_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--dry-run", "--quiet"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_cli_help_groups_options_and_examples(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="0"):
        main(["--help"])

    captured = capsys.readouterr()
    assert "Вход и результат" in captured.out
    assert "Интерфейс" in captured.out
    assert "Примеры:" in captured.out
    assert "--html" not in captured.out


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

    побеждает по приоритету. В contract_01.docx сущности сторон структурно
    кластеризуются в профиль (Поставщик/Покупатель) — ``PolicyAgent.apply``
    уже проверен на «голом» TYPE-победе без профиля юнит-тестом
    (``tests/masker/policy/test_apply.py::test_type_keep_answer_masks_only_that_type``);
    здесь достаточно снять оба профиля ответом «оставить», чтобы TYPE-ответ
    по некритичному типу реально долетел до keep, а критичный остался
    замаскирован гвардией. `contract_number` («ДОГОВОР ПОСТАВКИ № 44/2026»,
    план T2.2.1, шаг 10) не образует своего профиля — это факт о документе,
    не о стороне (`profile/agent.py::_DOCUMENT_LEVEL_TYPES`), уходит в
    отдельный вопрос `PROFILE-UNASSIGNED`, P1/P2 остаются
    Поставщиком/Покупателем, как и до появления детектора.
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
    assert report["report_version"] == 4
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
            ]
        )
        == 0
    )

    report = json.loads((tmp_path / "contract_01" / "report.json").read_text(encoding="utf-8"))
    assert report["decisions"]["critical_unmasked"]
    assert any("осознанн" in item.casefold() for item in report["limitations"])


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
    """T1.10, шаг 9 (решение Р1): ``redacted.docx`` заменён на ``masked_highlight.docx``."""
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    assert (
        main([str(src), "--out", str(tmp_path / "out"), "--rules-only", "--redact-style", "marker"])
        == 0
    )
    assert (tmp_path / "out" / "contract" / "masked_highlight.docx").exists()


def test_cli_docx_redact_permissions(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only", "--redact-style", "marker"])
    redacted = tmp_path / "out" / "contract" / "masked_highlight.docx"
    assert stat.S_IMODE(redacted.stat().st_mode) == 0o600


def test_cli_docx_no_redact_without_flag(tmp_path: Path) -> None:
    src = tmp_path / "contract.docx"
    _make_simple_docx(src)
    main([str(src), "--out", str(tmp_path / "out"), "--rules-only"])
    assert not (tmp_path / "out" / "contract" / "masked_highlight.docx").exists()
    assert not (tmp_path / "out" / "contract" / "masked_black.docx").exists()


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


def _install_fake_ocr_for_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Подменить `select_ocr` на FakeOCR с распознанным содержательным текстом."""
    from masker.ocr.fake import FakeOCR
    from masker.ocr.provider import OCRLine

    def _line(text: str, y: int) -> OCRLine:
        return OCRLine(
            text=text,
            bbox=(50.0, float(y), 50.0 + 10.0 * len(text), float(y + 20)),
            polygon=(
                (50.0, float(y)),
                (50.0 + 10.0 * len(text), float(y)),
                (50.0 + 10.0 * len(text), float(y + 20)),
                (50.0, float(y + 20)),
            ),
            confidence=1.0,
        )

    fake = FakeOCR(
        lines=(
            _line("Договор поставки товара №42", 80),
            _line("ИНН 7707083893 КПП 770701001", 180),
            _line("Стороны: ООО Ромашка и ИП Иванов И И", 280),
        )
    )
    monkeypatch.setattr("masker.cli.select_ocr", lambda: fake)


def _write_test_image(path: Path) -> None:
    from PIL import Image

    Image.new("RGB", (900, 1200), (255, 255, 255)).save(str(path), format="JPEG", dpi=(300, 300))


def test_cli_processes_image_and_returns_original_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`python -m masker file.jpg` → артефакт `masked_highlight.jpg`."""
    src = tmp_path / "contract.jpg"
    _write_test_image(src)
    _install_fake_ocr_for_image(monkeypatch)

    code = main(
        [
            str(src),
            "--out",
            str(tmp_path / "out"),
            "--rules-only",
            "--redact-style",
            "marker",
        ]
    )
    assert code in (0, EXIT_LEAK)
    artifact_dir = tmp_path / "out" / src.stem
    highlight = artifact_dir / "masked_highlight.jpg"
    assert highlight.is_file()


def test_cli_pdf_output_format_leaves_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--output-format=pdf` → артефакт `masked_highlight.pdf`, не картинка."""
    src = tmp_path / "contract.png"
    from PIL import Image

    Image.new("RGB", (900, 1200), (255, 255, 255)).save(str(src), format="PNG", dpi=(300, 300))
    _install_fake_ocr_for_image(monkeypatch)

    code = main(
        [
            str(src),
            "--out",
            str(tmp_path / "out"),
            "--rules-only",
            "--redact-style",
            "marker",
            "--output-format",
            "pdf",
        ]
    )
    assert code in (0, EXIT_LEAK)
    artifact_dir = tmp_path / "out" / src.stem
    assert (artifact_dir / "masked_highlight.pdf").is_file()
    assert not (artifact_dir / "masked_highlight.png").exists()


def test_help_survives_single_byte_console(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--help` не падает там, где консоль не знает кириллицы.

    Замерено в GitHub Actions (`Tests` #85, windows-latest): собранный
    бинарник падал на первой же команде с
    `UnicodeEncodeError: 'charmap' codec can't encode characters`, потому
    что консоль Windows по умолчанию в cp1252/cp866, а весь интерфейс
    DocVeil на русском. Здесь та же ситуация воспроизводится подменой
    кодировки потока.
    """
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")

    monkeypatch.setattr(sys, "stdout", stream)
    ensure_utf8_output()
    stream.write("Обезличить PII в DOCX/PDF\n")
    stream.flush()

    assert stream.encoding.lower() in {"utf-8", "utf8"}
