"""Р13: длина реквизита сохраняется после всех источников детекции."""

from __future__ import annotations

from dataclasses import dataclass

from masker.detect.agent import DetectAgent
from masker.detect.requisites import has_complete_requisite_length
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source


@dataclass
class _FragmentDetector:
    name: str = "fragment"
    source: Source = Source.RULE
    priority: int = 100

    def detect(self, document: Document) -> list[Entity]:
        return [
            Entity(
                type=EntityType.BANK_ACCOUNT,
                text="1 ",
                segment_order=0,
                start=0,
                end=2,
                source=Source.RULE,
                confidence=0.75,
            )
        ]


def test_requisite_lengths_are_definitions_not_minimum_heuristics() -> None:
    assert has_complete_requisite_length(EntityType.BANK_ACCOUNT, "4" * 20)
    assert has_complete_requisite_length(EntityType.BANK_ACCOUNT, "3" * 11)
    assert has_complete_requisite_length(EntityType.INN, "7" * 10)
    assert has_complete_requisite_length(EntityType.INN, "7" * 12)
    assert has_complete_requisite_length(EntityType.OGRN, "1" * 13)
    assert has_complete_requisite_length(EntityType.OGRN, "1" * 15)
    assert has_complete_requisite_length(EntityType.SNILS, "112-233-445 95")
    assert has_complete_requisite_length(EntityType.KPP, "7703A1001")
    assert has_complete_requisite_length(EntityType.BIK, "042007681")
    assert not has_complete_requisite_length(EntityType.BANK_ACCOUNT, "1 ")
    assert not has_complete_requisite_length(EntityType.INN, "7" * 9)
    assert not has_complete_requisite_length(EntityType.OGRN, "1" * 12)
    assert not has_complete_requisite_length(EntityType.SNILS, "1" * 10)
    assert not has_complete_requisite_length(EntityType.KPP, "77030100")
    assert not has_complete_requisite_length(EntityType.BIK, "04200768")


def test_detect_agent_never_passes_incomplete_requisite_to_plan() -> None:
    """Общий барьер отсекает обрывок даже от произвольного детектора."""
    document = Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment("1 ", Anchor("docx", ("body", 0)), 0)],
    )

    assert DetectAgent([_FragmentDetector()]).detect(document).entities == []
