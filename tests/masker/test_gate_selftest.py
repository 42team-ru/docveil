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
