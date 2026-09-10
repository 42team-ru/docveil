"""Граница слоя OCR: клиентские библиотеки не импортируются вне ``masker.ocr``.

Параллель с ``tests/masker/llm/test_layer_boundary.py``: смена OCR-движка
не должна трогать логику узлов графа. Единственный способ обеспечить это
механически — grep-по-AST на прямые импорты ``paddleocr``/``pytesseract``
за пределами ``src/masker/ocr/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[3] / "src" / "masker"
FORBIDDEN_MODULES = ("paddleocr", "pytesseract")


def test_no_ocr_imports_outside_layer() -> None:
    """Прямых импортов OCR-клиентов за пределами `masker.ocr` быть не должно."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        if _is_inside_ocr_layer(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module_name in _imported_module_names(node):
                top_level = module_name.split(".")[0]
                if top_level in FORBIDDEN_MODULES:
                    offenders.append(
                        f"{path.relative_to(SRC_ROOT.parent.parent)}: import {module_name}"
                    )
    assert not offenders, "прямые импорты OCR-клиентов вне masker.ocr:\n" + "\n".join(offenders)


def _is_inside_ocr_layer(path: Path) -> bool:
    return "ocr" in path.relative_to(SRC_ROOT).parts[:-1]


def _imported_module_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []
