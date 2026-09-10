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


# --- Р7-2: секция "verifier" в report.json ------------------------------------


def _verifier_report(*, verified: int = 1, unverified_by_reason: dict[str, int] | None = None):
    from masker.detect.verifier import VerifierReport, Window, WindowVerdict

    unverified_by_reason = unverified_by_reason or {}
    verdicts = []
    for index in range(verified):
        window = Window(id=f"w{index}", segment_order=0, start=0, end=10, text="Смирнова" * 1)
        verdicts.append(WindowVerdict(window=window, status="verified", reason=""))
    counter = verified
    for reason, count in unverified_by_reason.items():
        for _ in range(count):
            window = Window(id=f"w{counter}", segment_order=0, start=0, end=10, text=f"x{counter}")
            verdicts.append(WindowVerdict(window=window, status="unverified", reason=reason))
            counter += 1
    return VerifierReport(
        verdicts=tuple(verdicts),
        windows=len(verdicts),
        verified=verified,
        unverified=sum(unverified_by_reason.values()),
        unverified_by_reason=dict(unverified_by_reason),
        input_chars=42,
        document_chars=1000,
    )


def test_report_has_no_verifier_section_when_layer_did_not_run() -> None:
    """Слой выключен (``verifier=None``) — секции нет вовсе, а не пустая с
    нулями, имитирующая «проверено, ничего нет» (Р7-2)."""
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities

    report = _build_report(document, entities, with_plan=False)

    assert "verifier" not in report


def test_report_verifier_section_carries_counts_and_reasons() -> None:
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities
    index = EntityIndex(entities)
    ref_by_entity_id = {id(entity): index.ref(entity) for entity in entities}
    verifier_report = _verifier_report(
        verified=1, unverified_by_reason={"unmatched_quote": 2, "llm_error": 1}
    )

    report = build_report_payload(
        Path("input.docx"),
        document,
        entities,
        [],
        frozenset(),
        _DOCUMENT_COVERAGE,
        {},
        ref_by_entity_id=ref_by_entity_id,
        registry=EntityTypeRegistry.builtin(),
        verifier=verifier_report,
    )

    assert report["verifier"] == {
        "windows": 4,
        "verified": 1,
        "unverified": 3,
        "unverified_by_reason": {"llm_error": 1, "unmatched_quote": 2},
        "input_chars": 42,
        "document_chars": 1000,
        "input_share": 0.042,
        "r_filter": None,
    }


def test_report_verifier_section_carries_r_filter_when_measured() -> None:
    """``r_filter`` — null, пока вызывающий не измерил его по разметке
    (``measure_filter_coverage``); production-документ разметки не имеет,
    но канал должен пропускать значение, если оно всё же есть (например,
    диагностика на размеченном корпусе)."""
    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities

    report = build_report_payload(
        Path("input.docx"),
        document,
        entities,
        [],
        frozenset(),
        _DOCUMENT_COVERAGE,
        {},
        registry=EntityTypeRegistry.builtin(),
        verifier=_verifier_report(),
        r_filter=0.5,
    )

    assert report["verifier"]["r_filter"] == 0.5


def test_report_verifier_section_is_byte_identical_across_two_runs() -> None:
    """Инвариант детерминизма: два прогона одного документа дают побайтово
    одинаковую секцию ``verifier`` в ``report.json``."""
    import json

    document = ingest_docx(FIXTURES / "contract_03_ner.docx")
    entities = DetectAgent().detect(document).entities
    verifier_report = _verifier_report(verified=2, unverified_by_reason={"budget_exceeded": 1})

    def _build() -> dict:
        return build_report_payload(
            Path("input.docx"),
            document,
            entities,
            [],
            frozenset(),
            _DOCUMENT_COVERAGE,
            {},
            registry=EntityTypeRegistry.builtin(),
            verifier=verifier_report,
            r_filter=None,
        )

    first = json.dumps(_build()["verifier"], sort_keys=True, ensure_ascii=False)
    second = json.dumps(_build()["verifier"], sort_keys=True, ensure_ascii=False)
    assert first == second
