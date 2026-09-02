"""Граница cli.py: только argparse/LLM-конфиг/запись файлов/печать (T1.10, шаг 9).

Тест намеренно грубый — читает исходник построчно и ищет подстроки, а не
разбирает импорты через ``ast``: он фиксирует границу, которая иначе
расползётся обратно при первой же правке, добавившей «удобный» прямой
вызов агента в обход графа.

``render_html_report`` — единственное исключение из семейства ``render_*``:
HTML-отчёт остаётся на стороне вызывающего по решению раздела 0 плана
T1.10 (React возьмёт ``state["report"]`` напрямую, минуя файл, но CLI
сегодня продолжает уметь ``--html``), поэтому имя намеренно не входит в
список запрещённых подстрок ниже.
"""

from __future__ import annotations

from pathlib import Path

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
CLI_SOURCE = (ROOT / "src" / "masker" / "cli.py").read_text(encoding="utf-8")

#: Имена предметных агентов/парсеров/рендеров, которых в cli.py быть не
#: должно ни в каком виде (импорт, вызов, упоминание в тексте) — граница
#: держится не только на импортах, отсюда и грубый поиск по подстроке.
_FORBIDDEN_SUBSTRINGS = (
    "PlanAgent",
    "ValidateAgent",
    "DetectAgent",
    "ProfileAgent",
    "JudgeAgent",
    "ingest_docx",
    "ingest_pdf",
    "render_docx_preview",
    "render_docx_redacted",
    "render_pdf_preview",
    "render_pdf_redacted",
)


def test_cli_source_has_no_domain_agent_or_render_names() -> None:
    hits = [name for name in _FORBIDDEN_SUBSTRINGS if name in CLI_SOURCE]
    assert hits == [], f"cli.py содержит запрещённые имена: {hits}"


def test_cli_source_is_under_line_budget() -> None:
    """T1.10, шаг 9, критерий приёмки дословно: ``grep -c "" cli.py`` < 450."""
    assert len(CLI_SOURCE.splitlines()) < 450
