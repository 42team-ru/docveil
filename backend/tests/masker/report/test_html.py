"""Тесты HTML-отчёта: колонка «маркер» и блок «Группы согласованности» (T1.6, шаг 7)."""

from __future__ import annotations

from pathlib import Path

from masker.cli import main
from masker.report.html import _groups, _marker_legend, _pii_rows, _review_possible

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def test_html_report_shows_marker_column(tmp_path: Path) -> None:
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--types",
                "all",
                "--profile",
                "--html",
            ]
        )
        == 0
    )
    html = (tmp_path / FIXTURE.stem / "report.html").read_text(encoding="utf-8")

    assert "<th>Маркер</th>" in html
    assert "Группы согласованности" in html
    assert "[ПОСТАВЩИК-ИНН]" in html


def test_html_escapes_marker_and_sample() -> None:
    """Образец и маркер экранируются как обычный пользовательский текст.

    Прогонять через полноценный CLI ради значения с ``<``/``&`` в имени
    организации — заложник удачи детектора; проверяем экранирование прямо
    на функциях разметки блока групп и таблицы замен."""
    chunk = {
        "pii": [
            {
                "type": "org_name",
                "text": "<b>ООО Ромашка</b> & Ко",
                "source": "rule",
                "confidence": 1.0,
                "start": 0,
                "end": 10,
                "marker": "[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]",
            }
        ]
    }
    rows = _pii_rows(chunk)
    assert "<b>ООО Ромашка</b> & Ко" not in rows
    assert "&lt;b&gt;ООО Ромашка&lt;/b&gt; &amp; Ко" in rows

    report = {
        "plan": {
            "groups": [
                {
                    "id": "G1",
                    "marker": "[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]",
                    "type": "org_name",
                    "profile_id": "P1",
                    "ref_count": 3,
                    "sample": "<b>ООО Ромашка</b> & Ко",
                }
            ]
        }
    }
    groups_html = _groups(report)
    assert "<b>ООО Ромашка</b> & Ко" not in groups_html
    assert "&lt;b&gt;ООО Ромашка&lt;/b&gt; &amp; Ко" in groups_html


def test_groups_block_is_empty_but_present_without_plan() -> None:
    """`plan` может отсутствовать в старом report.json — блок не должен падать."""
    assert "Групп согласованности нет" in _groups({})
    assert "Групп согласованности нет" in _groups({"plan": {"groups": []}})


# ── легенда сокращений маркера (план М1, правило 6) ────────────────────────────


def test_marker_legend_block_renders_shown_canonical_and_pages() -> None:
    report = {
        "marker_legend": [
            {"shown_label": "[Ф1]", "canonical_label": "[ПОСТАВЩИК-ФИО-1]", "pages": [3, 5]}
        ]
    }
    html = _marker_legend(report)
    assert "[Ф1]" in html
    assert "[ПОСТАВЩИК-ФИО-1]" in html
    assert "3, 5" in html


def test_marker_legend_block_is_empty_but_present_without_section() -> None:
    """``marker_legend`` может отсутствовать в старом report.json — блок не
    должен падать, а не только «не быть пустым»."""
    assert "Сокращений маркера нет" in _marker_legend({})
    assert "Сокращений маркера нет" in _marker_legend({"marker_legend": []})


def test_marker_legend_escapes_labels() -> None:
    report = {
        "marker_legend": [{"shown_label": "<b>Ф1</b>", "canonical_label": "<i>X</i>", "pages": [1]}]
    }
    html = _marker_legend(report)
    assert "<b>Ф1</b>" not in html
    assert "&lt;b&gt;Ф1&lt;/b&gt;" in html


def test_html_report_includes_marker_legend_heading(tmp_path: Path) -> None:
    assert (
        main(
            [
                str(FIXTURE),
                "--out",
                str(tmp_path),
                "--types",
                "all",
                "--profile",
                "--html",
            ]
        )
        == 0
    )
    html = (tmp_path / FIXTURE.stem / "report.html").read_text(encoding="utf-8")
    assert "Легенда сокращений маркера" in html


# ── «снять одним кликом», уровень possible (Р8) ─────────────────────────────────


def test_review_possible_block_renders_group_row() -> None:
    report = {
        "review_possible": [
            {
                "marker": "[ФИО-3]",
                "type": "person",
                "type_title": "ФИО",
                "ref_count": 2,
                "sample": "Иванов И.И.",
            }
        ]
    }
    html = _review_possible(report)
    assert "[ФИО-3]" in html
    assert "Иванов И.И." in html


def test_review_possible_block_is_empty_but_present_without_section() -> None:
    assert "Групп уровня possible нет" in _review_possible({})
    assert "Групп уровня possible нет" in _review_possible({"review_possible": []})
