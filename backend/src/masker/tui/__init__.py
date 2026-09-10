"""Интерактивный терминальный интерфейс DocVeil.

Импорт Textual отложен до проверки TTY: ``docveil tui | cat`` обязан дать
диагностику, даже если дополнительная зависимость ещё не установлена.
"""

from __future__ import annotations

import sys


def launch_tui() -> int:
    """Запустить TUI или вернуть понятную ошибку для неинтерактивного ввода."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("ошибка: для DocVeil TUI нужен интерактивный терминал", file=sys.stderr)
        return 2
    try:
        from masker.tui.app import DocVeilApp
    except ImportError as error:
        print(f"ошибка: TUI недоступен, установите зависимость textual ({error})", file=sys.stderr)
        return 2
    DocVeilApp().run()
    return 0


__all__ = ["launch_tui"]
