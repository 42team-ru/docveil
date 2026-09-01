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
    masked_first = out_first / FIXTURE.stem / "masked_highlight.docx"
    masked_second = out_second / FIXTURE.stem / "masked_highlight.docx"
    with (
        zipfile.ZipFile(masked_first) as first_zip,
        zipfile.ZipFile(masked_second) as second_zip,
    ):
        assert first_zip.namelist() == second_zip.namelist()
        for name in first_zip.namelist():
            assert first_zip.read(name) == second_zip.read(name), name


def test_idempotent_second_pass_on_masked_document(tmp_path: Path) -> None:
    """Инвариант идемпотентности: повторный прогон по уже обезличенному
    документу не меняет ничего.

    Второй проход обязан не найти сущностей вовсе — иначе маркеры первого
    прохода сами похожи на PII, и каждый следующий прогон переписывал бы
    документ заново. Сырые байты контейнера сравнивать нельзя (`python-docx`
    штампует в заголовки zip время сохранения), поэтому сравнивается
    распакованное содержимое всех частей — то, что определяет документ.
    """
    args = [
        "--types",
        "all",
        "--redact-style",
        "blackbox",
        "--profile",
    ]
    first_out = tmp_path / "first"
    assert main([str(FIXTURE), "--out", str(first_out), *args]) == 0
    masked = first_out / FIXTURE.stem / "masked_black.docx"

    second_out = tmp_path / "second"
    assert main([str(masked), "--out", str(second_out), *args]) == 0
    report = json.loads((second_out / masked.stem / "report.json").read_text(encoding="utf-8"))

    assert report["entity_count"] == 0, f"второй проход нашёл сущности: {report['entities']}"
    assert report["plan"]["groups"] == []
    assert report["plan"]["skipped"]["count"] == 0

    twice_masked = second_out / masked.stem / "masked_black.docx"
    with zipfile.ZipFile(masked) as once, zipfile.ZipFile(twice_masked) as twice:
        assert once.namelist() == twice.namelist()
        for name in once.namelist():
            assert once.read(name) == twice.read(name), name
