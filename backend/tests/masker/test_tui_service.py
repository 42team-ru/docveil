"""Узкие проверки адаптера TUI без запуска Textual и настоящего графа."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from masker.run import RunOutcome
from masker.tui.service import TuiRunRequest, TuiRunService


def test_service_writes_unchanged_report_and_exposes_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.docx"
    source.touch()
    report = {"entity_count": 1, "entities": [{"type": "inn", "marker": "[ИНН]"}]}
    outcome = RunOutcome(
        "done",
        "thread",
        None,
        {"report": report, "artifacts": [{"role": "marker", "path": "/tmp/masked.docx"}]},
    )
    observed: list[tuple[str, str, str]] = []

    def fake_start_run(*_args: object, **kwargs: object) -> RunOutcome:
        deps = kwargs["deps"]
        assert hasattr(deps, "stage_observer")
        assert deps.stage_observer is not None
        deps.stage_observer("extract", "started", "")
        deps.stage_observer("extract", "completed", "готово")
        return outcome

    monkeypatch.setattr("masker.tui.service.start_run", fake_start_run)

    result = TuiRunService().run(
        TuiRunRequest(source=source, types=frozenset({"inn"}), out=tmp_path / "out"),
        lambda node, status, detail: observed.append((node, status, detail)),
    )

    assert json.loads(result.report_path.read_text(encoding="utf-8")) == report
    assert result.artifacts == [{"role": "marker", "path": "/tmp/masked.docx"}]
    assert observed == [("extract", "started", ""), ("extract", "completed", "готово")]
    assert result.report_path.stat().st_mode & 0o777 == 0o600


def test_service_rejects_empty_selection_before_graph(tmp_path: Path) -> None:
    source = tmp_path / "source.docx"
    source.touch()

    with pytest.raises(ValueError, match="хотя бы один тип"):
        TuiRunService().run(
            TuiRunRequest(source=source, types=frozenset(), out=tmp_path), lambda *_: None
        )


def test_service_rejects_missing_or_unsupported_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="существующий файл"):
        TuiRunService().run(
            TuiRunRequest(source=tmp_path / "source.txt", types=frozenset({"inn"}), out=tmp_path),
            lambda *_: None,
        )
