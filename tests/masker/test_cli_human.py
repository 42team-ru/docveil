"""CLI: две фазы человека в цикле — --ask/--resume/--answers/--fresh, коды 0/2/3/10."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import sys
from pathlib import Path

import pytest

from masker.cli import main

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def _read_questions(tmp_path: Path, stem: str = "contract_01") -> dict:
    return json.loads((tmp_path / stem / "questions.json").read_text(encoding="utf-8"))


def test_ask_pauses_and_writes_questions_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"])

    assert exit_code == 10
    questions_path = tmp_path / "contract_01" / "questions.json"
    assert questions_path.is_file()
    assert stat.S_IMODE(questions_path.stat().st_mode) == 0o600
    payload = json.loads(questions_path.read_text(encoding="utf-8"))
    assert payload["questions"]

    captured = capsys.readouterr()
    assert payload["thread_id"] in captured.out
    assert str(len(payload["questions"])) in captured.out
    for question in payload["questions"]:
        assert question["id"] in captured.out


def test_repeated_ask_gives_same_code_and_byte_identical_questions_json(tmp_path: Path) -> None:
    first_code = main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"])
    first_bytes = (tmp_path / "contract_01" / "questions.json").read_bytes()

    second_code = main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"])
    second_bytes = (tmp_path / "contract_01" / "questions.json").read_bytes()

    assert first_code == 10
    assert second_code == 10
    assert first_bytes == second_bytes


def test_resume_with_answers_completes_and_report_has_decisions(tmp_path: Path) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"]) == 10
    payload = _read_questions(tmp_path)
    thread_id = payload["thread_id"]

    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "thread_id": thread_id,
                "answers": {q["id"]: q["default"] for q in payload["questions"]},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
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

    assert exit_code == 0
    report = json.loads((tmp_path / "contract_01" / "report.json").read_text(encoding="utf-8"))
    assert "decisions" in report
    assert "final_actions" in report


def test_resume_unknown_thread_gives_code_3_and_no_new_files(tmp_path: Path) -> None:
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps({"schema_version": 1, "thread_id": "нет-такого", "answers": {}}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--resume",
            "нет-такого",
            "--out",
            str(tmp_path),
            "--profile",
            "--answers",
            str(answers_path),
        ]
    )

    assert exit_code == 3
    assert not (tmp_path / "contract_01").exists()


def test_repeated_resume_with_different_answers_gives_code_3_and_report_unchanged(
    tmp_path: Path,
) -> None:
    assert main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"]) == 10
    payload = _read_questions(tmp_path)
    thread_id = payload["thread_id"]

    answers_path = tmp_path / "answers.json"
    answers_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "thread_id": thread_id,
                "answers": {q["id"]: q["default"] for q in payload["questions"]},
            }
        ),
        encoding="utf-8",
    )
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
    before = hashlib.sha256(report_path.read_bytes()).digest()

    other_answers_path = tmp_path / "answers2.json"
    other_answers_path.write_text(
        json.dumps({"schema_version": 1, "thread_id": thread_id, "answers": {}}),
        encoding="utf-8",
    )
    exit_code = main(
        [
            "--resume",
            thread_id,
            "--out",
            str(tmp_path),
            "--profile",
            "--answers",
            str(other_answers_path),
        ]
    )

    assert exit_code == 3
    after = hashlib.sha256(report_path.read_bytes()).digest()
    assert before == after


def test_non_ask_run_completes_with_closed_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO())

    exit_code = main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only"])

    assert exit_code == 0


def test_ask_without_profile_gives_code_2(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main([str(FIXTURE), "--out", str(tmp_path), "--rules-only", "--ask"])


def test_answers_without_ask_completes_in_one_call(tmp_path: Path) -> None:
    """`--answers` допустим и в первой фазе: прерывания вообще не возникает."""
    exit_code = main([str(FIXTURE), "--out", str(tmp_path), "--profile", "--rules-only", "--ask"])
    assert exit_code == 10
    payload = _read_questions(tmp_path)
    answers_path = tmp_path / "answers.json"
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

    # Другой, свежий тред (--fresh) сразу с ответами — ни одного прерывания.
    exit_code = main(
        [
            str(FIXTURE),
            "--out",
            str(tmp_path),
            "--profile",
            "--rules-only",
            "--answers",
            str(answers_path),
            "--fresh",
        ]
    )

    assert exit_code == 0
    report = json.loads((tmp_path / "contract_01" / "report.json").read_text(encoding="utf-8"))
    assert "decisions" in report


def test_files_or_resume_required(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="2"):
        main(["--out", str(tmp_path), "--profile"])
