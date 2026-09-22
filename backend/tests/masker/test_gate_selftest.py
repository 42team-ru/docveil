"""Ворота, которые всегда зелёные, хуже отсутствия ворот.

Здесь проверяется, что ворота умеют не пройти: заведомо нарушенный инвариант
обязан дать ненулевой код возврата.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
_NEUTRAL_PROFILE_JUDGE_METRICS = {
    "cluster_purity": 1.0,
    "role_coverage": 1.0,
    "role_accuracy": 1.0,
    "critical_in_questions": 0.0,
    "questions_per_document": 0.0,
    "policy_questions_per_document": 0.0,
    "critical_unmasked": 0.0,
}


def _fixture_corpus(name: str) -> list[tuple[Path, dict[str, Any]]]:
    """Один реальный документ для проверки конкретного инварианта ворот.

    Self-test не калибрует метрики: он доказывает, что gate замечает уже
    внесённый дефект. Полный корпус здесь лишь повторял ту же проверку много
    раз и делал два unit-теста самыми долгими во всём наборе.
    """
    from masker.eval import load_corpus

    corpus = [item for item in load_corpus() if item[0].name == name]
    assert len(corpus) == 1, f"в корпусе должна быть ровно одна фикстура {name!r}"
    return corpus


def _layout_fixture_corpus(tmp_path: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Минимальный PDF, в котором соседние строки перекрываются по высоте.

    Это та же доказанная геометрия Д10, что у unit-тестов PDF-рендера: без
    ``_trim_to_own_line`` область удаления ИНН задевает живой текст второй
    строки. Один лист заменяет 30-страничную производственную фикстуру в
    self-test именно *механизма ворот*.
    """
    import pymupdf

    path = tmp_path / "overlapping-lines.pdf"
    font = ROOT / "src" / "masker" / "data" / "DejaVuSans.ttf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname="dvu", fontfile=str(font))
    page.insert_text((72, 100), "ИНН 3662103003", fontname="dvu", fontsize=13)
    page.insert_text((72, 112.7), "Соседняя строка остаётся", fontname="dvu", fontsize=13)
    document.save(str(path))
    document.close()
    return [(path, {"entities": [{"type": "inn", "text": "3662103003"}]})]


def test_pytest_step_can_fail(tmp_path) -> None:
    failing = tmp_path / "test_broken.py"
    failing.write_text(
        textwrap.dedent("""
        def test_deliberately_broken() -> None:
            assert False, "нарочно сломанный инвариант"
    """)
    )
    rc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(failing)],
        capture_output=True,
        text=True,
    ).returncode
    assert rc != 0, "шаг «тесты» в воротах не умеет падать"


def test_checksum_step_can_fail() -> None:
    from masker.detect.checksums import is_valid_inn

    assert is_valid_inn("3662103003")
    assert not is_valid_inn("3662103004"), "контрольная сумма ИНН ничего не проверяет"


def test_critical_unmasked_metric_can_fail(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """Снятие маски с критичного типа без двойного подтверждения обязано

    ронять ``masker.eval --gate`` — раздел 3 плана T1.5.1, инвариант
    ``critical_unmasked == 0`` для неинтерактивного прогона.
    """
    import masker.eval as eval_module
    from masker.policy.agent import CriticalUnmask

    # Self-test ворот проверяет реакцию метрики, а не доступность GigaChat.
    monkeypatch.setenv("MASKER_LLM_PROFILE", "fake")
    original_apply = eval_module.PolicyAgent.apply
    corpus = _fixture_corpus("contract_04_bankruptcy.docx")

    assert eval_module.run(gate=True, corpus=corpus, include_supplementary=False) == 0
    capsys.readouterr()

    def broken_apply(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_apply(self, *args, **kwargs)
        result.critical_unmasked = [
            CriticalUnmask(question_id="TYPE-inn", kind="type", target="inn", count=1)
        ]
        return result

    monkeypatch.setattr(eval_module.PolicyAgent, "apply", broken_apply)

    code = eval_module.run(
        gate=True,
        corpus=corpus,
        include_supplementary=False,
    )
    output = capsys.readouterr().out
    assert code != 0, "ворота не заметили снятую маску с критичного типа"
    assert "критичный тип снят без двойного подтверждения (critical_unmasked)" in output


def test_layout_step_can_fail(monkeypatch, capsys, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """План T2.2.2, шаг 5: ворота обязаны заметить, что прямоугольник
    редакции стёр текст соседней строки (Д10) — метрика ``layout_removed_chars``
    обязана назвать провал по имени, а не просто вернуть ненулевой код.

    Ломаем ``_trim_to_own_line`` так, чтобы обрезка по соседней строке не
    применялась вовсе — ровно поведение до шага 3 плана T2.2.2, которое и
    породило Д10 на реальном документе.
    """
    import masker.eval as eval_module
    import masker.render.pdf_render as pdf_render_module

    corpus = _layout_fixture_corpus(tmp_path)
    monkeypatch.setattr(
        eval_module,
        "_profile_judge_metrics",
        lambda _corpus: dict(_NEUTRAL_PROFILE_JUDGE_METRICS),
    )
    assert eval_module.run(gate=True, corpus=corpus, include_supplementary=False) == 0
    capsys.readouterr()

    def _no_trim(rect, own_line_id, line_boxes):  # type: ignore[no-untyped-def]
        return rect, False

    monkeypatch.setattr(pdf_render_module, "_trim_to_own_line", _no_trim)

    code = eval_module.run(
        gate=True,
        corpus=corpus,
        include_supplementary=False,
    )
    output = capsys.readouterr().out
    assert code != 0, "ворота не заметили потерю текстового слоя вне замен (Д10)"
    metric_line = next(
        line for line in output.splitlines() if line.startswith("layout_removed_chars")
    )
    assert int(metric_line.split()[-1]) > 0, metric_line
    assert "layout_removed_chars " in output and "прямоугольник редакции стёр текст" in output


def test_validate_step_can_fail(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """T1.8, шаг 11: ворота обязаны краснеть, когда рендер пропустил замену.

    Ворота, которые всегда зелёные, хуже отсутствия ворот. Здесь проверяется
    не сам ``ValidateAgent`` (это тесты в ``tests/masker/validate/``), а
    последнее звено: полный прогон CLI при найденной утечке обязан вернуть
    ``EXIT_LEAK``, а не записать её в ``report.json`` и молча выйти нулём.

    Ломаем ``_redact_paragraph``, отбрасывая одну замену: остальные маркеры
    расставлены, документ выглядит обезличенным — ровно тот дефект, который
    глазами не ловится.
    """
    import masker.render.docx_redact as docx_redact
    from masker.cli import EXIT_LEAK, main

    fixture = ROOT / "fixtures" / "labeled" / "contract_02_hard.docx"
    args = [str(fixture), "--types", "all", "--redact-style", "marker"]
    assert main([*args, "--out", str(tmp_path / "clean")]) == 0, (
        "фикстура обязана проходить чисто, иначе тест доказывает не то"
    )

    original = docx_redact._redact_paragraph

    def skip_one(paragraph, replacements, style, highlight_background):  # type: ignore[no-untyped-def]
        original(paragraph, replacements[:-1], style, highlight_background)

    monkeypatch.setattr(docx_redact, "_redact_paragraph", skip_one)

    assert main([*args, "--out", str(tmp_path / "broken")]) == EXIT_LEAK, (
        "CLI вернул 0, хотя Validate обязан был увидеть пропущенную замену"
    )
