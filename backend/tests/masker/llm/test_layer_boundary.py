"""Граница слоя LLM: провайдер-специфичные импорты не должны утекать наружу.

Требование заказчика №6 — смена GigaChat на локальную модель не должна
трогать логику узлов. Единственный способ гарантировать это механически —
запретить прямой импорт клиентских библиотек (`gigachat`, `openai`) везде,
кроме `src/masker/llm/`.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "masker"
FORBIDDEN_MODULES = ("gigachat", "openai")


def test_no_llm_imports_outside_layer() -> None:
    """Grep-по-AST: import gigachat/openai встречается только внутри llm/."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if _is_inside_llm_layer(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module_name in _imported_module_names(node):
                top_level = module_name.split(".")[0]
                if top_level in FORBIDDEN_MODULES:
                    offenders.append(
                        f"{path.relative_to(SRC_ROOT.parent.parent)}: import {module_name}"
                    )
    assert not offenders, "прямые импорты LLM-клиентов вне masker.llm:\n" + "\n".join(offenders)


def _is_inside_llm_layer(path: Path) -> bool:
    return "llm" in path.relative_to(SRC_ROOT).parts[:-1]


def _imported_module_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []
