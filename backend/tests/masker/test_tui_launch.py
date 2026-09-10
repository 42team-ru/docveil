"""Точка входа TUI не должна пытаться открыть экран в пайпе или CI."""

from __future__ import annotations

from masker.cli import main


def test_tui_in_non_tty_has_friendly_error(capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["tui"]) == 2
    assert "нужен интерактивный терминал" in capsys.readouterr().err
