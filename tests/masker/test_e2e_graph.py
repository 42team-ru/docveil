"""Сквозной прогон полного графа: extract → ... → report (T1.10, шаг 10).

Единственный путь CLI (шаг 9) — этот файл гоняет его целиком, не по узлам
и не по кускам: ``--profile --redact-style both`` через ``main()`` с
настоящим SQLite-чекпойнтером на ``tmp_path``, как в проде.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from masker.cli import main

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def test_full_graph_run_produces_both_artifacts_and_clean_validation(tmp_path: Path) -> None:
    exit_code = main(
        [
            str(FIXTURE),
            "--out",
            str(tmp_path),
            "--profile",
            "--types",
            "all",
            "--redact-style",
            "both",
        ]
    )

    assert exit_code == 0
    artifact_dir = tmp_path / FIXTURE.stem
    assert (artifact_dir / "preview.docx").is_file()
    assert (artifact_dir / "masked_highlight.docx").is_file()
    assert (artifact_dir / "masked_black.docx").is_file()

    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    assert report["validation"]["status"] == "checked"
    assert report["validation"]["ok"] is True
    assert report["leaked"] == []
    assert report["plan"]["groups"]

    # Число абзацев цело в обоих редактирующих рендерах — инвариант
    # «структура цела» (AGENTS.md), не только «утечки нет».
    from docx import Document as open_docx

    original_paragraphs = len(open_docx(str(FIXTURE)).paragraphs)
    for name in ("masked_highlight.docx", "masked_black.docx"):
        redacted = open_docx(str(artifact_dir / name))
        assert len(redacted.paragraphs) == original_paragraphs


def test_full_graph_run_is_byte_reproducible_across_output_directories(tmp_path: Path) -> None:
    """Тот же документ, два разных ``--out`` — распакованно одинаковые артефакты.

    Дополняет ``test_two_cli_runs_give_byte_identical_report``
    (``masked_highlight.docx``) проверкой второго стиля — ``masked_black.docx``
    и распакованного ``preview.docx`` — раз уж полный прогон и так уже
    оплачен этим тестом.
    """
    out_first = tmp_path / "first"
    out_second = tmp_path / "second"
    args = [
        str(FIXTURE),
        "--profile",
        "--types",
        "all",
        "--redact-style",
        "both",
    ]
    assert main([*args, "--out", str(out_first)]) == 0
    assert main([*args, "--out", str(out_second)]) == 0

    def _unzipped(path: Path) -> dict[str, bytes]:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    for name in ("preview.docx", "masked_highlight.docx", "masked_black.docx"):
        first = _unzipped(out_first / FIXTURE.stem / name)
        second = _unzipped(out_second / FIXTURE.stem / name)
        assert first == second, name
