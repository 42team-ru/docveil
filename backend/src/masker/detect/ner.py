"""Локальный NER-детектор Natasha для ФИО и названий организаций."""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from masker.detect.normalize import normalize_value
from masker.detect.orgforms import (
    expand_org_span,
    fix_person_initials,
    has_organization_evidence,
    is_landmark_place,
    is_organization_form_only,
    is_partial_org_form,
    is_public_body,
    is_role_phrase,
    is_role_stopword,
    shrink_span,
)
from masker.detect.persons import (
    drop_role_prefix,
    expand_person_left,
    person_stem,
    preceded_by_address_marker,
    single_token_person_is_confirmed,
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


class MemoizedNerTagger:
    """Кэшировать результат NER по тексту сегмента для нескольких детекторов."""

    def __init__(self, delegate: NerTagger) -> None:
        @functools.lru_cache(maxsize=2048)
        def spans_for_text(text: str) -> tuple[NerSpan, ...]:
            return tuple(delegate.spans(text))

        self._spans_for_text: Callable[[str], tuple[NerSpan, ...]] = spans_for_text

    def spans(self, text: str) -> list[NerSpan]:
        return list(self._spans_for_text(text))


def memoize_tagger(tagger: NerTagger) -> NerTagger:
    """Вернуть теггер с кэшем по значению текста сегмента."""
    return MemoizedNerTagger(tagger)


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
    types = frozenset(LABEL_TO_TYPE.values())

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
                if entity_type is EntityType.PERSON:
                    # Должность прочь, фамилия слева — план T2.2.1, шаг 6, Д4.
                    bounds = drop_role_prefix(segment.text, *bounds)
                    if bounds is None:
                        continue
                    bounds = expand_person_left(segment.text, *bounds)
                start, end = bounds
                value = segment.text[start:end]
                org_evidence = entity_type is EntityType.ORG_NAME and has_organization_evidence(
                    value
                )
                if (
                    is_role_stopword(value)
                    # is_landmark_place «применяется только к спанам без
                    # признаков организации» по своему же докстрингу — без
                    # этой защиты «Школьно-базовая столовая № 11» (стем
                    # landmark_stems «школ») дропалась бы даже с оргформой
                    # и кавычками рядом (план T2.2.1, шаг 5, Д5).
                    or (is_landmark_place(value) and not org_evidence)
                    or (
                        entity_type is EntityType.ORG_NAME
                        and (
                            is_organization_form_only(value)
                            or is_partial_org_form(value)
                            or is_public_body(value)
                            or is_role_phrase(value)
                            or (not has_organization_evidence(value) and len(value.split()) == 1)
                        )
                    )
                    # «ул. Банникова» — Банникова улица, не фамилия (Д4
                    # наоборот, план T2.2.1, шаг 7).
                    or (
                        entity_type is EntityType.PERSON
                        and preceded_by_address_marker(segment.text, start)
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
        return self._require_person_evidence(found, document)

    @staticmethod
    def _require_person_evidence(found: list[Entity], document: Document) -> list[Entity]:
        """Однотокенный PER выпускается только с независимым подтверждением
        (план T2.2.1, шаг 7): та же фамилия встречается с инициалами/именем
        в другом месте документа, либо рядом стоит триггер («директор»,
        «в лице», ...). Без этой защиты расширение границ (шаг 6) сделало
        бы шире и существующие ложные срабатывания («Мармит», «Суп»,
        «Амортизац», «Корректировочных»).
        """
        confirmed_stems = frozenset(
            stem
            for entity in found
            if entity.type is EntityType.PERSON and len(entity.text.split()) > 1
            for stem in person_stem(entity.text).split()
            if stem
        )
        texts = {segment.order: segment.text for segment in document.segments}
        return [
            entity
            for entity in found
            if entity.type is not EntityType.PERSON
            or single_token_person_is_confirmed(
                entity.text, texts[entity.segment_order], entity.start, confirmed_stems
            )
        ]
