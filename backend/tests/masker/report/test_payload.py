"""Уровень уверенности (Р8) в report.json: entity/summary/groups/review_possible."""

from __future__ import annotations

from pathlib import Path

from masker.detect.agent import DetectAgent
from masker.entity_types import EntityTypeRegistry
from masker.ingest.docx_ingest import ingest_docx
from masker.mask import PlanAgent
from masker.model import ConfidenceLevel
from masker.refs import EntityIndex
from masker.report.payload import build_report_payload

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
