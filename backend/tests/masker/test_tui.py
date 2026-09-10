"""Headless Textual-проверки экранов DocVeil через App.run_test и Pilot."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("textual")

from masker.tui.app import DocVeilApp, FileScreen, HelpScreen, ResultScreen
from masker.tui.service import StageObserver, TuiRunRequest, TuiRunResult


class FakeService:
    """Быстрый детерминированный ответ вместо LangGraph в UI-тесте."""

    def run(self, _request: TuiRunRequest, observe: StageObserver) -> TuiRunResult:
        observe("extract", "started", "")
        observe("extract", "completed", "готово")
        return TuiRunResult(
            report={
                "entity_count": 1,
                "entities": [
                    {
                        "type": "inn",
                        "marker": "[ПОСТАВЩИК-ИНН]",
                        "confidence": 1.0,
                        "anchor": {"label": "Абзац 2"},
                    }
                ],
                "telemetry": {"llm": {"message": "Потрачено 0"}},
                "contract_summary": {"contract_number": "[ДОГОВОР]"},
                "certificate": {"ok": True},
                "verifier": {"verified": 1, "windows": 1},
            },
            report_path=Path("out/report.json"),
            artifacts=[{"role": "marker", "path": "out/masked.docx"}],
            runtime_metrics_path=Path("out/runtime-metrics.json"),
        )


@pytest.mark.asyncio
async def test_help_opens_from_welcome() -> None:
    app = DocVeilApp(service=FakeService())

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("?")
        assert isinstance(app.screen, HelpScreen)


@pytest.mark.asyncio
async def test_run_displays_result_table_without_terminal() -> None:
    app = DocVeilApp(service=FakeService())

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.click("#start")
        file_screen = app.screen
        assert isinstance(file_screen, FileScreen)
        file_screen.select_path(Path("contract.docx"))
        await pilot.click("#next")
        await pilot.click("#run")
        await pilot.pause(delay=0.1)

        assert isinstance(app.screen, ResultScreen)
        assert app.screen.query_one("#entities").row_count == 1
        assert "Потрачено 0" in str(app.screen.query_one("#run-summary").render())
