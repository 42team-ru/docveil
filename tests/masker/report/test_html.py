"""Тесты HTML-отчёта: колонка «маркер» и блок «Группы согласованности» (T1.6, шаг 7)."""

from __future__ import annotations

from pathlib import Path

from masker.cli import main
from masker.report.html import _groups, _pii_rows

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
