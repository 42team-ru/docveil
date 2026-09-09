"""Уровень уверенности (Р8) в report.json: entity/summary/groups/review_possible."""

from __future__ import annotations

from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.mask import PlanAgent
from masker.model import Certificate, CertificateCheck, ConfidenceLevel, ValidationReport
from masker.refs import EntityIndex
from masker.report.payload import (
    _validation_record,
    _validation_skipped,
    build_report_payload,
    marker_legend,
)

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"
_DOCUMENT_COVERAGE = {"tables": {"nested_count": 0}}


def _build_report(document, entities, *, with_plan: bool) -> dict:
    index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): index.ref(entity) for entity in entities}
    plan = PlanAgent().plan(document, entities, requested_types=None) if with_plan else None
    return build_report_payload(
        Path("input.docx"),
        document,
        entities,
        [],
        frozenset(),
        _DOCUMENT_COVERAGE,
        {},
        ref_by_entity_id=ref_by_entity_id,
        plan=plan,
        registry=EntityTypeRegistry.builtin(),
    )


def test_entity_record_carries_confidence_level() -> None:
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities
    assert {entity.level.value for entity in entities} >= {
        ConfidenceLevel.CONFIRMED.value,
        ConfidenceLevel.POSSIBLE.value,
    }, "фикстура должна содержать оба уровня, иначе тест ничего не проверяет"

    report = _build_report(document, entities, with_plan=False)

    by_text = {item["text"]: item["level"] for item in report["entities"]}
    for entity in entities:
        assert by_text[entity.text] == entity.level.value


def test_summary_by_level_counts_match_entities() -> None:
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities

    report = _build_report(document, entities, with_plan=False)

    by_level = report["summary"]["by_level"]
    assert sum(by_level.values()) == len(entities)
    for level in (ConfidenceLevel.CONFIRMED, ConfidenceLevel.PROBABLE, ConfidenceLevel.POSSIBLE):
        expected = sum(1 for entity in entities if entity.level == level)
        assert by_level.get(level.value, 0) == expected


def test_review_possible_section_lists_only_possible_groups() -> None:
    """Р8, требование 3 таблицы: «possible» выносится в отчёте отдельной
    секцией «снять одним кликом» — ``report["review_possible"]``."""
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities

    report = _build_report(document, entities, with_plan=True)

    assert report["plan"]["groups"], "план должен построить хотя бы одну группу"
    possible_groups = [g for g in report["plan"]["groups"] if g["level"] == "possible"]
    assert possible_groups, "фикстура должна содержать хотя бы одну группу уровня possible"
    assert report["review_possible"] == possible_groups
    # Ни одна confirmed-группа не должна утечь в «снять одним кликом».
    confirmed_ids = {g["id"] for g in report["plan"]["groups"] if g["level"] == "confirmed"}
    review_ids = {g["id"] for g in report["review_possible"]}
    assert not (confirmed_ids & review_ids)


def test_review_possible_is_empty_list_without_plan() -> None:
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities

    report = _build_report(document, entities, with_plan=False)

    assert report["review_possible"] == []
    assert "plan" not in report


# ── легенда сокращений маркера (план М1, правило 6) ────────────────────────────


def _degradation(
    *,
    shown_label: str,
    canonical_label: str,
    page: int,
    fallback_reason: str = "compact",
) -> dict[str, object]:
    return {
        "artifact": "masked_highlight.pdf",
        "role": "masked_highlight",
        "page": page,
        "group_id": "G1",
        "entity_type": "person",
        "canonical_label": canonical_label,
        "shown_label": shown_label,
        "font_size": 8.0,
        "fallback_reason": fallback_reason,
    }


def test_marker_legend_is_empty_without_degradations() -> None:
    assert marker_legend([]) == []


def test_marker_legend_maps_shown_to_canonical_with_human_page_numbers() -> None:
    """Пример из плана М1: ``[Ф1] = [ПОСТАВЩИК-ФИО-1], стр. 3`` — страница
    человекочитаемая (с 1), а не 0-based индекс PyMuPDF, которым оперирует
    рендер (``item["page"]`` в ``render_degradations`` — 0-based)."""
    legend = marker_legend(
        [_degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=2)]
    )
    assert legend == [{"shown_label": "[Ф1]", "canonical_label": "[ПОСТАВЩИК-ФИО-1]", "pages": [3]}]


def test_marker_legend_aggregates_pages_and_deduplicates() -> None:
    """Один и тот же сокращённый маркер встречается на нескольких страницах
    — легенда даёт одну строку с отсортированным списком уникальных страниц,
    а не строку на каждое вхождение."""
    legend = marker_legend(
        [
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=4),
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=2),
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=2),
        ]
    )
    assert legend == [
        {"shown_label": "[Ф1]", "canonical_label": "[ПОСТАВЩИК-ФИО-1]", "pages": [3, 5]}
    ]


def test_marker_legend_keeps_different_canonical_labels_separate() -> None:
    """Два профиля с разными ролями никогда не схлопываются в одну короткую
    метку (план М1, критерий приёмки) — легенда обязана отражать это же
    свойство отдельными строками, если оно вдруг нарушится."""
    legend = marker_legend(
        [
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=1),
            _degradation(shown_label="[Ф2]", canonical_label="[ПОКУПАТЕЛЬ-ФИО-1]", page=1),
        ]
    )
    assert legend == [
        {"shown_label": "[Ф1]", "canonical_label": "[ПОСТАВЩИК-ФИО-1]", "pages": [2]},
        {"shown_label": "[Ф2]", "canonical_label": "[ПОКУПАТЕЛЬ-ФИО-1]", "pages": [2]},
    ]


def test_marker_legend_skips_blank_fallback_with_no_visible_marker() -> None:
    """Ступень «blank» (``shown_label == ""``) ничего не вписывает в
    документ — расшифровывать в легенде нечего, строка не создаётся."""
    legend = marker_legend(
        [
            _degradation(
                shown_label="",
                canonical_label="[ПОСТАВЩИК-ФИО-1]",
                page=1,
                fallback_reason="blank",
            )
        ]
    )
    assert legend == []


def test_marker_legend_skips_entries_without_real_degradation() -> None:
    """Защита от вырожденного случая: ``shown_label`` совпал с
    ``canonical_label`` (деградации по факту не было) — строка легенды не
    нужна, показывать нечего расшифровывать."""
    legend = marker_legend(
        [
            _degradation(
                shown_label="[ПОСТАВЩИК-ФИО-1]",
                canonical_label="[ПОСТАВЩИК-ФИО-1]",
                page=1,
                fallback_reason="",
            )
        ]
    )
    assert legend == []


def test_marker_legend_order_is_deterministic_regardless_of_input_order() -> None:
    """Два прогона на разном порядке деградаций (может отличаться порядком
    обхода страниц/групп) обязаны дать одинаковую легенду — детерминизм
    отчёта (инвариант проекта)."""
    forward = marker_legend(
        [
            _degradation(shown_label="[Ф2]", canonical_label="[ПОКУПАТЕЛЬ-ФИО-1]", page=5),
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=1),
        ]
    )
    backward = marker_legend(
        [
            _degradation(shown_label="[Ф1]", canonical_label="[ПОСТАВЩИК-ФИО-1]", page=1),
            _degradation(shown_label="[Ф2]", canonical_label="[ПОКУПАТЕЛЬ-ФИО-1]", page=5),
        ]
    )
    assert forward == backward
    assert [item["shown_label"] for item in forward] == ["[Ф1]", "[Ф2]"]


# ── _validation_record: сертификат обезличивания в report.json (план М3) ─────────


def test_validation_record_serializes_certificate() -> None:
    """``report["validation"]["certificate"]`` — сериализованный
    ``Certificate`` целиком, а не только его ``ok``: заказчик должен увидеть
    все три пункта с обоснованием, а не одно булево значение."""
    certificate = Certificate(
        ok=False,
        checks=(
            CertificateCheck(name="leak_scan", ok=True, detail="утечек не найдено"),
            CertificateCheck(name="metadata_cleared", ok=True, detail="метаданные пусты"),
            CertificateCheck(name="width_quantization", ok=False, detail="ширина не кратна 12pt"),
        ),
    )
    report = ValidationReport(
        leaked=(),
        residual=(),
        checked_artifacts=("masked_black.pdf",),
        checked_parts=("page 1",),
        ok=True,
        certificate=certificate,
    )
    record = _validation_record(report)
    assert record["certificate"]["ok"] is False
    assert [check["name"] for check in record["certificate"]["checks"]] == [
        "leak_scan",
        "metadata_cleared",
        "width_quantization",
    ]
    assert record["certificate"]["checks"][2]["ok"] is False


def test_validation_record_certificate_none_when_not_computed() -> None:
    """``ValidationReport`` собран напрямую без сертификата (тесты, старый
    код) — ``record["certificate"]`` явно ``None``, а не отсутствует."""
    report = ValidationReport(
        leaked=(), residual=(), checked_artifacts=(), checked_parts=(), ok=True
    )
    record = _validation_record(report)
    assert record["certificate"] is None


def test_validation_skipped_has_no_certificate_key() -> None:
    """``preview_only`` — сертификат не считался вовсе, не «прошёл вникуда»."""
    skipped = _validation_skipped("preview_only: --redact-style не задан")
    assert "certificate" not in skipped
