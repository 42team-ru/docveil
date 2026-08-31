"""Детерминизм: два полных прогона с одинаковыми ответами дают одинаковые артефакты.

Раздел 9 плана T1.5.1: ``report.json`` и ``questions.json`` не зависят от
времени, ``Interrupt.id`` (недетерминирован — доказано пробоем) и порядка
входных словарей.
"""

from __future__ import annotations

import json
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
