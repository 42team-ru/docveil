"""validate_node — утечка кладётся в State как данные, не как исключение (T1.10, шаг 6)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from masker.graph import nodes
from masker.graph.state import State
from masker.render import docx_redact as docx_redact_module

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def _rendered_state(tmp_path: Path, *, styles: tuple[str, ...]) -> State:
    state: State = {
        "path": str(FIXTURE),
        "options": {
            "rules_only": True,
            "types": None,
            "interactive": False,
            "styles": list(styles),
            "preview": True,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.make_detect_node(nodes.RunDeps())(state))
    state.update(nodes.plan_node(state))
    render_node = nodes.make_render_node(nodes.RunDeps(artifact_dir=tmp_path))
    state.update(render_node(state))
    return state


def test_validate_node_reports_leak_as_data_and_reaches_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Рендер, «забывший» одну замену, даёт непустой ``leaked`` без исключения.

    Патч ставится на сам модуль ``docx_redact_module`` (риск R2 плана T1.10,
    раздел 10): ``render_node`` обязан звать функцию рендера через атрибут
    модуля, а не через раскрытое при импорте имя — иначе этот патч тихо
    переставал бы попадать в цель, и тест зеленел бы, ничего не проверяя.
    """
    original_redact = docx_redact_module.render_docx_redacted
    calls = 0

    def broken_redact(
        source: object,
        destination: object,
        document: object,
        plan: object,
        *,
        style: str = "marker",
        highlight_background: str | None = "#FFDE66",
    ) -> None:
        nonlocal calls
        calls += 1
        truncated = dataclasses.replace(plan, replacements=plan.replacements[:-1])  # type: ignore[arg-type]
        original_redact(  # type: ignore[arg-type]
            source,
            destination,
            document,
            truncated,
            style=style,
            highlight_background=highlight_background,
        )

    monkeypatch.setattr(docx_redact_module, "render_docx_redacted", broken_redact)

    state = _rendered_state(tmp_path, styles=("marker",))

    result = nodes.validate_node(state)

    assert calls == 1  # подмена действительно вызвалась — не позеленело мимо цели
    assert result["leaked"]
    assert result["validation"]["ok"] is False
    assert result["validation"]["status"] == "checked"


def test_validate_node_skips_when_no_redacting_artifacts(tmp_path: Path) -> None:
    state = _rendered_state(tmp_path, styles=())

    result = nodes.validate_node(state)

    assert result["validation"] == {
        "status": "skipped",
        "reason": "preview_only: --redact-style не задан",
    }
    assert result["leaked"] == []


def test_validate_node_clean_artifact_has_no_leaks(tmp_path: Path) -> None:
    state = _rendered_state(tmp_path, styles=("marker",))

    result = nodes.validate_node(state)

    assert result["validation"]["ok"] is True
    assert result["leaked"] == []
