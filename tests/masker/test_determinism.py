"""Детерминизм: два полных прогона с одинаковыми ответами дают одинаковые артефакты.

Раздел 9 плана T1.5.1: ``report.json`` и ``questions.json`` не зависят от
времени, ``Interrupt.id`` (недетерминирован — доказано пробоем) и порядка
входных словарей.
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


def _full_run(out: Path, *, fresh: bool) -> tuple[bytes, bytes]:
    args = [str(FIXTURE), "--out", str(out), "--profile", "--rules-only", "--ask"]
    if fresh:
        args.append("--fresh")
    assert main(args) == 10

    questions_path = out / FIXTURE.stem / "questions.json"
    questions_bytes = questions_path.read_bytes()
    payload = json.loads(questions_bytes)
    answers_path = out / "answers.json"
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "thread_id": payload["thread_id"],
                "answers": {q["id"]: q["default"] for q in payload["questions"]},
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--resume",
                payload["thread_id"],
                "--out",
                str(out),
                "--profile",
                "--answers",
                str(answers_path),
            ]
        )
        == 0
    )
    report_bytes = (out / FIXTURE.stem / "report.json").read_bytes()
    return questions_bytes, report_bytes


def test_two_full_runs_with_same_answers_are_byte_identical(tmp_path: Path) -> None:
    first_questions, first_report = _full_run(tmp_path, fresh=False)
    second_questions, second_report = _full_run(tmp_path, fresh=True)

    assert first_questions == second_questions
    assert first_report == second_report


def test_two_cli_runs_give_byte_identical_report(tmp_path: Path) -> None:
    """T1.6, шаг 6: план (маркеры, группы, ``skipped``) не должен вносить
    недетерминизм в простой CLI-путь (без ``--ask``) при ``--redact-style``."""
    out_first = tmp_path / "first"
    out_second = tmp_path / "second"

    args = [
        str(FIXTURE),
        "--redact-style",
        "marker",
        "--profile",
        "--types",
        "all",
    ]
    assert main([*args, "--out", str(out_first)]) == 0
    assert main([*args, "--out", str(out_second)]) == 0

    report_first = (out_first / FIXTURE.stem / "report.json").read_bytes()
    report_second = (out_second / FIXTURE.stem / "report.json").read_bytes()
    assert report_first == report_second

    # Сырые байты .docx как контейнера сравнивать нельзя: `python-docx`
    # пишет в заголовок каждой записи zip текущее время сохранения
    # (разрешение 2 секунды), это внешний артефакт библиотеки, а не наш
    # недетерминизм. Сравниваем распакованное содержимое частей архива —
    # то, что реально определяет обезличенный документ.
    redacted_first = out_first / FIXTURE.stem / "redacted.docx"
    redacted_second = out_second / FIXTURE.stem / "redacted.docx"
    with (
        zipfile.ZipFile(redacted_first) as first_zip,
        zipfile.ZipFile(redacted_second) as second_zip,
    ):
        assert first_zip.namelist() == second_zip.namelist()
        for name in first_zip.namelist():
            assert first_zip.read(name) == second_zip.read(name), name
