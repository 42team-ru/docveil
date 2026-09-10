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


def test_supported_formats_have_a_single_source() -> None:
    """Список форматов не должен существовать в двух местах.

    До 10.09.2026 копий было шесть, и две протухли: движок уже разбирал
    XLSX, а CLI и API отвечали «формат не поддерживается». Формат, который
    работает в воротах и не работает в продукте, не ловится ни одним
    тестом — поэтому проверяем сам факт единственного источника.
    """
    from api.services.run_service import SUPPORTED_SUFFIXES as api_suffixes
    from masker.bench import _GRAPH_SUPPORTED_SUFFIXES as bench_suffixes
    from masker.cli import SUPPORTED_SUFFIXES as cli_suffixes
    from masker.ingest import SUPPORTED_SUFFIXES as engine_suffixes

    assert cli_suffixes is engine_suffixes
    assert api_suffixes is engine_suffixes
    assert bench_suffixes is engine_suffixes


def test_engine_parses_every_declared_format() -> None:
    """Объявленный формат обязан иметь разбор в графе, а не только в списке."""
    from masker.graph import nodes
    from masker.ingest import SUPPORTED_SUFFIXES

    source = Path(nodes.__file__).read_text(encoding="utf-8")
    for suffix in SUPPORTED_SUFFIXES:
        assert f'== "{suffix}"' in source, f"граф не разбирает объявленный формат {suffix}"
