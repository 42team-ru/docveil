"""Локальный NER-детектор Natasha для ФИО и названий организаций."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Protocol

from masker.detect.normalize import normalize_value
from masker.detect.orgforms import (
    expand_org_span,
    fix_person_initials,
    has_organization_evidence,
    is_organization_form_only,
    is_public_body,
    is_role_stopword,
    shrink_span,
)
from masker.model import Document, Entity, EntityType, Source


@dataclass(frozen=True, slots=True)
class NerSpan:
    """Минимальное представление спана, возвращаемого моделью."""

    start: int
    end: int
    label: str


class NerTagger(Protocol):
    """Минимум, который нужен детектору от любой NER-модели."""

    def spans(self, text: str) -> list[NerSpan]:
        """Вернуть модельные спаны с локальными смещениями."""


class _NatashaTagger:
    def __init__(self) -> None:
        from natasha import NewsEmbedding, NewsNERTagger, Segmenter

        self._segmenter = Segmenter()
        self._tagger = NewsNERTagger(NewsEmbedding())

    def spans(self, text: str) -> list[NerSpan]:
        from natasha import Doc

        doc = Doc(text)
        doc.segment(self._segmenter)
        doc.tag_ner(self._tagger)
        return [NerSpan(span.start, span.stop, span.type) for span in doc.spans]


@functools.lru_cache(maxsize=1)
def natasha_tagger() -> NerTagger:
    """Собрать Natasha один раз за процесс, не импортируя её при импорте модуля."""
    return _NatashaTagger()


#: Априорная оценка точности слоя по типу. НЕ измерение: корпус слишком мал,
#: чтобы назначать это число. Корпус только ограничивает его сверху и снизу —
#: см. test_ner_confidence_is_calibrated.
NER_CONFIDENCE: dict[EntityType, float] = {
    EntityType.PERSON: 0.85,
    EntityType.ORG_NAME: 0.80,
}

LABEL_TO_TYPE: dict[str, EntityType] = {
    "PER": EntityType.PERSON,
    "ORG": EntityType.ORG_NAME,
}


class NatashaDetector:
    """NER Natasha по сегментам.

    Метка ``LOC`` игнорируется, детектор не производит ``ADDRESS`` ни при
    каких входных данных; адрес — задача T1.14.
    """

    name = "natasha"
    source = Source.NER
    priority = 50

    def __init__(self, tagger: NerTagger | None = None) -> None:
        self._tagger = tagger

    def detect(self, document: Document) -> list[Entity]:
        """Найти ФИО и названия организаций с локальными смещениями сегментов."""
        tagger = self._tagger or natasha_tagger()
        found: list[Entity] = []
        for segment in document.segments:
            for span in tagger.spans(segment.text):
                entity_type = LABEL_TO_TYPE.get(span.label)
                if entity_type is None:
                    continue
                bounds = (
                    expand_org_span(segment.text, span.start, span.end)
                    if entity_type is EntityType.ORG_NAME
                    else fix_person_initials(segment.text, span.start, span.end)
                )
                if bounds is None:
                    continue
                bounds = shrink_span(segment.text, *bounds)
                if bounds is None:
                    continue
                start, end = bounds
                value = segment.text[start:end]
                if is_role_stopword(value) or (
                    entity_type is EntityType.ORG_NAME
                    and (
                        is_organization_form_only(value)
                        or is_public_body(value)
                        or (len(value.split()) == 1 and not has_organization_evidence(value))
                    )
                ):
                    continue
                found.append(
                    Entity(
                        type=entity_type,
                        text=value,
                        segment_order=segment.order,
                        start=start,
                        end=end,
                        source=Source.NER,
                        confidence=NER_CONFIDENCE[entity_type],
                        normalized=normalize_value(entity_type, value),
                    )
                )
        return found
