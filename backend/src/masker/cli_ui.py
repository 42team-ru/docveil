"""Интерфейс командной строки без предметной логики графа.

TTY получает краткий Rich-индикатор, перенаправленный вывод — только обычные
строки. Ничего из этого модуля не становится частью State или report.json.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

_STAGES: tuple[tuple[str, str], ...] = (
    ("extract", "Извлечение текста"),
    ("detect", "Поиск данных"),
    ("profile", "Определение сторон"),
    ("judge", "Проверка спорного"),
    ("policy", "Применение правил"),
    ("plan", "Планирование замен"),
    ("summary", "Сводка документа"),
    ("render", "Создание файлов"),
    ("validate", "Проверка утечек"),
    ("report", "Сборка отчёта"),
)
_STAGE_LABELS = dict(_STAGES)


class CliPresenter:
    """Показывает прогресс и результаты, оставляя не-TTY вывод машиночитаемым."""

    def __init__(self, *, quiet: bool, verbose: bool) -> None:
        self._quiet = quiet
        self._verbose = verbose and not quiet
        self._interactive = sys.stdout.isatty() and not quiet
        self._started = time.monotonic()
        self._completed: set[str] = set()
        self._console = Console()
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None

    def begin(self, source: Path) -> None:
        """Начать отображение одного запуска файла."""
        self._started = time.monotonic()
        self._completed.clear()
        if self._quiet:
            return
        if not self._interactive:
            print(f"{source}: обработка начата")
            return
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
            transient=True,
        )
        self._progress.start()
        self._task_id = self._progress.add_task("Подготовка", total=len(_STAGES))

    def observe(self, node: str, status: str, message: str = "") -> None:
        """Принять уведомление об узле графа из ``RunDeps``."""
        if self._quiet:
            return
        label = _STAGE_LABELS.get(node, node.replace("_", " "))
        if status == "started":
            self._show_current(label)
            return
        if status != "completed":
            return
        if node in _STAGE_LABELS and node not in self._completed:
            self._completed.add(node)
            self._show_completed(label)
        if self._verbose and message:
            self._write(f"  {label}: {message}")

    def finish_progress(self) -> float:
        """Остановить и очистить индикатор, вернуть фактическую длительность."""
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None
        return time.monotonic() - self._started

    def dry_run(self, source: Path, *, types: str, profile: bool, styles: str | None) -> None:
        """Показать план операции без вызова графа и без записи артефактов."""
        if self._quiet:
            return
        target = styles or "только preview"
        print(f"{source}: предпросмотр, файлы не будут записаны")
        print(f"  типы: {types}; профили: {'да' if profile else 'нет'}; выходы: {target}")

    def questions(self, thread_id: str, questions: list[dict[str, Any]], path: Path) -> None:
        """Напечатать пакет вопросов для паузы графа."""
        if self._quiet:
            return
        print(f"thread_id: {thread_id}")
        print(f"вопросов: {len(questions)}")
        for question in questions:
            options = ", ".join(str(item) for item in question["options"])
            print(f"  [{question['id']}] {question['prompt']} — варианты: {options}")
        print(f"  файл вопросов: {path}")

    def result(
        self,
        source: Path,
        report: Mapping[str, object],
        artifacts: list[dict[str, object]],
        report_path: Path,
        *,
        thread_id: str,
        html_path: Path | None,
        trace_paths: tuple[Path, Path] | None,
        elapsed_seconds: float,
    ) -> None:
        """Напечатать стабильную итоговую сводку после успешного прогона."""
        if self._quiet:
            return
        summary = _mapping(report.get("summary"))
        by_type = _mapping(summary.get("by_type"))
        found = (
            ", ".join(f"{name}: {count}" for name, count in sorted(by_type.items())) or "не найдены"
        )
        plan = _mapping(report.get("plan"))
        replacements = sum(_ref_count(_mapping(item)) for item in _sequence(plan.get("groups")))
        usage = _mapping(_mapping(report.get("telemetry")).get("llm"))
        cost = str(usage.get("message", "Стоимость модели не рассчитывалась."))
        print(f"{source}: прогон завершён, thread_id {thread_id}")
        print(f"  найдено: {found}; замен: {replacements}")
        print(f"  длительность: {_format_duration(elapsed_seconds)}; {cost}")
        print(f"  отчёт: {report_path}")
        for item in artifacts:
            print(f"  {item['role']}: {item['path']}")
        if html_path is not None:
            print(f"  HTML:  {html_path}")
        if trace_paths is not None:
            print(f"  LLM-трейс:  {trace_paths[0]}")
            print(f"  LLM-трейс (человекочитаемый): {trace_paths[1]}")
            print(
                "  ВНИМАНИЕ: файлы llm-trace содержат исходные PII в открытом виде "
                "и не предназначены для передачи наружу."
            )
        profile_judge = _mapping(report.get("profile_judge"))
        if profile_judge:
            print(
                "  профили: "
                f"{len(_sequence(profile_judge.get('profiles')))}; "
                f"LLM-вызовы: {profile_judge.get('llm_calls', 0)}; "
                f"вопросы: {len(_sequence(profile_judge.get('questions')))}"
            )
            for diagnostic in _sequence(profile_judge.get("diagnostics")):
                print(f"  диагностика LLM: {diagnostic}")
        print("ВАЖНО: preview содержит исходный текст и служит только для проверки детектора.")

    def info(self, message: str) -> None:
        """Напечатать штатное сообщение с учётом --quiet."""
        if not self._quiet:
            self._write(message)

    def _show_current(self, label: str) -> None:
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description=label)

    def _show_completed(self, label: str) -> None:
        completed = len(self._completed)
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, completed=completed, description=label)
        elif not self._interactive:
            print(f"  {completed}/{len(_STAGES)}: {label}")

    def _write(self, message: str) -> None:
        if self._progress is not None:
            self._console.print(message)
        else:
            print(message)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, dict) else {}


def _sequence(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} с"
    minutes, rest = divmod(round(seconds), 60)
    return f"{minutes} мин {rest} с"


def _ref_count(group: Mapping[str, object]) -> int:
    value = group.get("ref_count", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
