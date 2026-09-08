#!/usr/bin/env python3
"""Прогресс по TASKS.md: сколько задач закрыто в каждом разделе.

Читает статусы из `TASKS.md` — строку вида `` `[x]` · `бэкенд` · … `` под
заголовком задачи. Источник истины один: сам TASKS.md, никакого второго
списка задач, который разъедется с первым.

Запуск: `make tasks` (или `python scripts/tasks_progress.py`).
Печатается также в конце `make gate` — прогресс полезнее всего ровно
тогда, когда только что стало известно, зелёные ворота или нет.
"""

from __future__ import annotations

import pathlib
import re
import sys

#: Буква раздела → человеческое имя. Порядок словаря = порядок вывода
#: (разделы TASKS.md идут в этом же порядке, от метрик к защите).
SECTIONS: dict[str, str] = {
    "К": "Доказательства качества",
    "Р": "Распознавание",
    "М": "Маскирование",
    "И": "ИИ-слой GigaChat",
    "Д": "Понимание договора",
    "В": "Веб-приложение",
    "З": "Защита и инфраструктура",
}

#: `### Р5 — Организации…` — заголовок задачи; буква раздела в группе 1.
_HEADING = re.compile(r"^### ([" + "".join(SECTIONS) + r"])(\d+) — (.+)$")
#: `` `[x]` · `бэкенд` · … `` — статус первой строкой под заголовком.
_STATUS = re.compile(r"^`\[([ x~])\]`")

_WIDTH = 12
_GREEN, _YELLOW, _DIM, _BOLD, _RESET = "\033[32m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"


def _color(text: str, code: str) -> str:
    """Красить только в настоящий терминал: в пайпе и в логах ворот
    escape-последовательности только мешают читать."""
    return f"{code}{text}{_RESET}" if sys.stdout.isatty() else text


def parse(path: pathlib.Path) -> dict[str, list[tuple[str, str, str]]]:
    """Раздел → список задач ``(идентификатор, статус, название)``."""
    found: dict[str, list[tuple[str, str, str]]] = {letter: [] for letter in SECTIONS}
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading is None:
            continue
        letter, number, title = heading.groups()
        # Статус ищем в ближайших строках: между заголовком и статусом
        # может стоять предупреждение-цитата (`> ⚠ …`) или пустая строка.
        status = " "
        for probe in lines[index + 1 : index + 5]:
            marker = _STATUS.match(probe)
            if marker is not None:
                status = marker.group(1)
                break
        found[letter].append((f"{letter}{number}", status, title))
    return found


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    tasks = root / "TASKS.md"
    if not tasks.is_file():
        print(f"TASKS.md не найден: {tasks}", file=sys.stderr)
        return 1

    sections = parse(tasks)
    total_done = total_all = 0
    in_progress: list[tuple[str, str]] = []

    print()
    print(_color("ПРОГРЕСС ПО TASKS.md", _BOLD))
    for letter, name in SECTIONS.items():
        items = sections[letter]
        if not items:
            continue
        done = sum(1 for _, status, _ in items if status == "x")
        started = sum(1 for _, status, _ in items if status == "~")
        total_done += done
        total_all += len(items)
        in_progress += [(ident, title) for ident, status, title in items if status == "~"]

        # Полоса длиной _WIDTH: закрытые задачи заполнены, начатые —
        # штриховкой, ещё не начатые — фоном. Длина ячейки на задачу
        # одинакова во всех разделах, поэтому полосы сравнимы на глаз.
        per = _WIDTH / len(items)
        filled = round(done * per)
        half = round(started * per)
        bar = "█" * filled + "▒" * half + "░" * (_WIDTH - filled - half)
        code = _GREEN if done == len(items) else (_YELLOW if done or started else _DIM)
        print(f"  {letter}  {name:<26} {done}/{len(items):<3} {_color(bar, code)}")

    percent = 100 * total_done / total_all if total_all else 0.0
    print(f"\n  всего закрыто: {total_done}/{total_all}  ({percent:.0f}%)")
    if in_progress:
        print(_color("  в работе:", _YELLOW))
        for ident, title in in_progress:
            print(f"    {ident} — {title}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
