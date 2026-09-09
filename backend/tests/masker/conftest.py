"""Общие тяжёлые заготовки для graph-тестов masker."""

from __future__ import annotations

from pathlib import Path

import pytest

from masker.graph import nodes
from masker.graph.state import State

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
PDF_FIXTURE = ROOT / "fixtures" / "labeled" / "contract_pdf_02_school.pdf"


@pytest.fixture(scope="session")
def planned_pdf_state() -> State:
    """PDF-состояние после plan, общее для проверок graph-проводки.

    Разбор и детекция этого производственного PDF не являются предметом
    проверок render/report-node. Один раз собранное состояние потребители
    копируют перед рендером, чтобы ни один тест не разделял изменяемый
    ``State`` с другим.
    """
    state: State = {
        "path": str(PDF_FIXTURE),
        "options": {
            "rules_only": False,
            "types": None,
            "interactive": False,
            "styles": ["marker"],
            "preview": False,
        },
    }
    state.update(nodes.extract_node(state))
    state.update(nodes.make_detect_node(nodes.RunDeps())(state))
    state.update(nodes.plan_node(state))
    return state
