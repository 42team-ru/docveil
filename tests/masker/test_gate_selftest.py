"""Ворота, которые всегда зелёные, хуже отсутствия ворот.

Здесь проверяется, что ворота умеют не пройти: заведомо нарушенный инвариант
обязан дать ненулевой код возврата.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)


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


def test_critical_unmasked_metric_can_fail(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Снятие маски с критичного типа без двойного подтверждения обязано

    ронять ``masker.eval --gate`` — раздел 3 плана T1.5.1, инвариант
    ``critical_unmasked == 0`` для неинтерактивного прогона.
    """
    import masker.eval as eval_module
    from masker.policy.agent import CriticalUnmask

    original_apply = eval_module.PolicyAgent.apply

    def broken_apply(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_apply(self, *args, **kwargs)
        result.critical_unmasked = [
            CriticalUnmask(question_id="TYPE-inn", kind="type", target="inn", count=1)
        ]
        return result

    monkeypatch.setattr(eval_module.PolicyAgent, "apply", broken_apply)

    assert eval_module.run(gate=True) != 0, "ворота не заметили снятую маску с критичного типа"


def test_layout_step_can_fail(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """План T2.2.2, шаг 5: ворота обязаны заметить, что прямоугольник
    редакции стёр текст соседней строки (Д10) — метрика ``layout_removed_chars``
    обязана назвать провал по имени, а не просто вернуть ненулевой код.

    Ломаем ``_trim_to_own_line`` так, чтобы обрезка по соседней строке не
    применялась вовсе — ровно поведение до шага 3 плана T2.2.2, которое и
    породило Д10 на реальном документе.
    """
    import masker.eval as eval_module
    import masker.render.pdf_render as pdf_render_module

    def _no_trim(rect, own_line_id, line_boxes):  # type: ignore[no-untyped-def]
        return rect, False

    monkeypatch.setattr(pdf_render_module, "_trim_to_own_line", _no_trim)

    code = eval_module.run(gate=True)
    output = capsys.readouterr().out
    assert code != 0, "ворота не заметили потерю текстового слоя вне замен (Д10)"
    metric_line = next(
        line for line in output.splitlines() if line.startswith("layout_removed_chars")
    )
    assert int(metric_line.split()[-1]) > 0, metric_line
    assert any("layout_removed_chars" in line for line in output.splitlines() if "> 0" in line), (
        output
    )


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

    def skip_one(paragraph, replacements, style):  # type: ignore[no-untyped-def]
        original(paragraph, replacements[:-1], style)

    monkeypatch.setattr(docx_redact, "_redact_paragraph", skip_one)

    assert main([*args, "--out", str(tmp_path / "broken")]) == EXIT_LEAK, (
        "CLI вернул 0, хотя Validate обязан был увидеть пропущенную замену"
    )
