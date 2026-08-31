"""Ворота, которые всегда зелёные, хуже отсутствия ворот.

Здесь проверяется, что ворота умеют не пройти: заведомо нарушенный инвариант
обязан дать ненулевой код возврата.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap


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
