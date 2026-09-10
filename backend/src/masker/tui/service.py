"""Адаптер графового прогона для TUI без виджетов и Textual.

Сервис не меняет State или ``report.json``: граф по-прежнему является
единственным местом, где строятся сущности, план и сертификат.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masker.graph.nodes import RunDeps
from masker.ocr.select import select_ocr
from masker.run import (
    RunFailedError,
    RunOptions,
    artifacts_of,
    report_of,
    sqlite_checkpointer_factory,
    start_run,
)

SUPPORTED_SUFFIXES = frozenset({".docx", ".pdf", ".xlsx"})
StageObserver = Callable[[str, str, str], None]


@dataclass(frozen=True, slots=True)
class TuiRunRequest:
    """Выбор оператора, достаточный для одного безопасного прогона."""

    source: Path
    types: frozenset[str]
    out: Path = Path("out") / "inspect"


@dataclass(frozen=True, slots=True)
class TuiRunResult:
    """Данные, которые TUI показывает после завершения графа."""

    report: dict[str, Any]
    report_path: Path
    artifacts: list[dict[str, Any]]
    runtime_metrics_path: Path


class TuiRunService:
    """Запускает граф с наблюдателем, не привязываясь к Textual."""

    def run(self, request: TuiRunRequest, observe: StageObserver) -> TuiRunResult:
        """Выполнить выбранный документ и сохранить стандартный отчёт рядом с ним."""
        source = request.source.resolve()
        if not source.is_file() or source.suffix.casefold() not in SUPPORTED_SUFFIXES:
            allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise ValueError(f"выберите существующий файл одного из форматов: {allowed}")
        if not request.types:
            raise ValueError("выберите хотя бы один тип данных для маскирования")

        artifact_dir = request.out.resolve() / source.stem
        selected = tuple(sorted(request.types))
        options = RunOptions(
            types=selected,
            profile=True,
            interactive=False,
            styles=("marker", "blackbox"),
            preview=True,
        )
        try:
            outcome = start_run(
                source,
                options,
                checkpointer_factory=sqlite_checkpointer_factory(
                    request.out.resolve() / "state.sqlite"
                ),
                deps=RunDeps(
                    artifact_dir=artifact_dir,
                    ocr=select_ocr(),
                    stage_observer=observe,
                ),
                fresh=True,
            )
        except RunFailedError as error:
            raise RuntimeError(str(error)) from error
        if outcome.status != "done":
            raise RuntimeError("прогон ожидает ответов оператора; откройте его через обычный CLI")
        report = report_of(outcome)
        report_path = artifact_dir / "report.json"
        _write_json(report_path, report)
        return TuiRunResult(
            report=report,
            report_path=report_path,
            artifacts=artifacts_of(outcome),
            runtime_metrics_path=artifact_dir / "runtime-metrics.json",
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
