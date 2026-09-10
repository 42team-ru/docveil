"""Тесты HTML-отчёта: колонка «маркер» и блок «Группы согласованности» (T1.6, шаг 7)."""

from __future__ import annotations

from pathlib import Path

from masker.cli import main
from masker.report.html import (
    _certificate_section,
    _groups,
    _marker_legend,
    _pii_rows,
    _review_possible,
    _verifier_section,
)

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


# ── верификатор на recall (Р7-2) ─────────────────────────────────────────────


def test_verifier_section_absent_shows_did_not_run_message() -> None:
    """Слой не включался (старый ``report.json`` без ключа, либо ``verifier``
    не запускался в этом прогоне) — явное сообщение, а не выдуманные нули."""
    assert "не запускался" in _verifier_section({})
    assert "не запускался" in _verifier_section({"verifier": None})


def test_verifier_section_renders_counts_and_r_filter() -> None:
    report = {
        "verifier": {
            "windows": 4,
            "verified": 1,
            "unverified": 3,
            "unverified_by_reason": {"unmatched_quote": 2, "llm_error": 1},
            "input_chars": 42,
            "document_chars": 1000,
            "input_share": 0.042,
            "r_filter": 0.5,
        }
    }
    html = _verifier_section(report)
    assert "0.500" in html
    assert "4.2%" in html
    assert "unmatched_quote" in html
    assert "2" in html


def test_verifier_section_shows_r_filter_not_measured_when_null() -> None:
    """``r_filter`` отсутствует у production-документа без разметки — блок
    обязан явно сказать «не измерен», а не показать 0 (0 означало бы
    «измерен и равен нулю»)."""
    report = {
        "verifier": {
            "windows": 1,
            "verified": 1,
            "unverified": 0,
            "unverified_by_reason": {},
            "input_chars": 10,
            "document_chars": 100,
            "input_share": 0.1,
            "r_filter": None,
        }
    }
    assert "не измерен" in _verifier_section(report)


# ── сертификат обезличивания (план М3) ──────────────────────────────────────────


def test_certificate_section_shows_ok_and_all_three_checks() -> None:
    report = {
        "certificate": {
            "ok": True,
            "checks": [
                {"name": "leak_scan", "ok": True, "detail": "утечек не найдено"},
                {"name": "metadata_cleared", "ok": True, "detail": "метаданные пусты"},
                {"name": "width_quantization", "ok": True, "detail": "кратно 12pt"},
            ],
        }
    }
    html = _certificate_section(report)
    assert "Сертификат пройден" in html
    assert "СЕРТИФИКАТ НЕ ПРОЙДЕН" not in html
    assert "пройдена" in html
    assert "ПРОВАЛЕНА" not in html
    for title in (
        "Побайтовый поиск утечек",
        "Метаданные вычищены",
        "не выдаёт длину оригинала",
    ):
        assert title in html


def test_certificate_section_shows_failure_banner_and_row_class() -> None:
    report = {
        "certificate": {
            "ok": False,
            "checks": [
                {"name": "leak_scan", "ok": True, "detail": "утечек не найдено"},
                {"name": "metadata_cleared", "ok": True, "detail": "метаданные пусты"},
                {
                    "name": "width_quantization",
                    "ok": False,
                    "detail": "R1 (person, стр. 1): ширина 68.20pt не кратна 12pt",
                },
            ],
        }
    }
    html = _certificate_section(report)
    assert "СЕРТИФИКАТ НЕ ПРОЙДЕН" in html
    assert "ПРОВАЛЕНА" in html
    assert 'class="cert-fail-row"' in html
    assert "68.20pt" in html


def test_certificate_section_escapes_detail() -> None:
    report = {
        "certificate": {
            "ok": False,
            "checks": [
                {"name": "leak_scan", "ok": False, "detail": "<script>alert(1)</script>"},
            ],
        }
    }
    html = _certificate_section(report)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_certificate_section_is_empty_but_present_without_section() -> None:
    """``report["certificate"]`` может быть ``None`` (preview_only) или
    отсутствовать (старый report.json) — блок явно говорит «не посчитан»,
    а не притворяется пройденным."""
    assert "не посчитан" in _certificate_section({})
    assert "не посчитан" in _certificate_section({"certificate": None})


def test_html_report_includes_certificate_heading(tmp_path: Path) -> None:
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
    assert "Сертификат обезличивания" in html
