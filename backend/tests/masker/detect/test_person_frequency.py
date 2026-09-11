"""Регрессии Р15: частая роль стороны не должна становиться персоной."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from masker.detect.agent import DetectAgent
from masker.ingest.pdf_ingest import ingest_pdf
from masker.model import Anchor, Document, Entity, EntityType, Segment, Source


def _document(value: str, occurrences: int) -> Document:
    return Document(
        path="test.pdf",
        fmt="pdf",
        segments=[
            Segment(text=value, anchor=Anchor("pdf", ("page", order)), order=order)
            for order in range(occurrences)
        ],
    )


@dataclass
class _RepeatedPersonDetector:
    value: str
    occurrences: int
    source: Source = Source.NER

    name = "repeated_person"
    priority = 50
    types: frozenset[str] = frozenset({EntityType.PERSON})

    def detect(self, document: Document) -> list[Entity]:
        return [
            Entity(
                type=EntityType.PERSON,
                text=self.value,
                segment_order=order,
                start=0,
                end=len(self.value),
                source=self.source,
            )
            for order in range(self.occurrences)
        ]


def _persons(value: str, occurrences: int, source: Source = Source.NER) -> list[str]:
    result = DetectAgent([_RepeatedPersonDetector(value, occurrences, source)]).detect(
        _document(value, occurrences)
    )
    return [entity.text for entity in result.entities if entity.type == EntityType.PERSON]


@pytest.mark.parametrize("source", [Source.NER, Source.RULE, Source.BLOCK])
def test_frequent_common_noun_is_not_person(source: Source) -> None:
    """Частая роль стороны — не имя независимо от источника кандидата."""
    assert _persons("Абонент", 8, source) == []


def test_real_contract_subscriber_role_is_not_person() -> None:
    """Р15: частая роль из договора связи не выходит из детекции как PERSON."""
    fixture = (
        Path(__file__).parents[3]
        / "fixtures"
        / "real-contracts"
        / "open-contracts"
        / "eat-654000009321.pdf"
    )
    persons = [
        entity.text
        for entity in DetectAgent().detect(ingest_pdf(fixture)).entities
        if entity.type == EntityType.PERSON
    ]
    assert "Абонент" not in persons


def test_surname_repeated_six_times_is_still_person() -> None:
    """Шесть упоминаний Бугакиной в договоре не дают права потерять фамилию."""
    assert _persons("Бугакина", 6) == ["Бугакина"] * 6
