"""Оркестрация подключаемых детекторов PII."""

from __future__ import annotations

import re
from collections.abc import Iterable

from masker.detect.base import EntityDetector
from masker.detect.normalize import normalize_value
from masker.detect.orgforms import (
    has_organization_evidence,
    is_organization_form_only,
    is_role_stopword,
    shrink_span,
)
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.detect.sweep import sweep
from masker.model import Document, Entity, EntityType, Source

MIN_FRAGMENT_LEN = 2


def _overlaps(first: Entity, second: Entity) -> bool:
    return (
        first.segment_order == second.segment_order
        and first.start < second.end
        and second.start < first.end
    )


class DetectAgent:
    """Объединяет детекторы, проверяет их контракт и строит общие чанки."""

    def __init__(self, detectors: Iterable[EntityDetector] | None = None) -> None:
        if detectors is None:
            from masker.detect import default_detectors

            detectors = default_detectors()
        self._detectors = list(detectors)

    @property
    def detectors(self) -> tuple[EntityDetector, ...]:
        """Подключённые детекторы в порядке их запуска."""
        return tuple(self._detectors)

    @staticmethod
    def _validate(detector: EntityDetector, document: Document, entities: list[Entity]) -> None:
        segments = {segment.order: segment for segment in document.segments}
        for entity in entities:
            segment = segments.get(entity.segment_order)
            if segment is None:
                raise ValueError(f"Detector {detector.name!r} returned an unknown segment_order")
            if not isinstance(entity.type, EntityType):
                raise ValueError(f"Detector {detector.name!r} returned an invalid entity type")
            if not isinstance(entity.source, Source):
                raise ValueError(f"Detector {detector.name!r} returned an invalid entity source")
            if not 0 <= entity.start < entity.end <= len(segment.text):
                raise ValueError(f"Detector {detector.name!r} returned an invalid entity span")
            if entity.text != segment.text[entity.start : entity.end]:
                raise ValueError(
                    f"Detector {detector.name!r} returned entity text outside its span"
                )

    @staticmethod
    def _resolve_overlaps(found: list[tuple[EntityDetector, Entity]]) -> list[Entity]:
        ordered = sorted(
            found,
            key=lambda item: (
                -item[0].priority,
                -item[1].confidence,
                -(item[1].end - item[1].start),
                item[1].type.value,
                item[1].segment_order,
                item[1].start,
                item[1].end,
                item[0].name,
            ),
        )
        accepted: list[Entity] = []
        for _detector, entity in ordered:
            overlaps = [existing for existing in accepted if _overlaps(entity, existing)]
            if not overlaps:
                accepted.append(entity)
                continue
            if entity.source is Source.RULE:
                continue
            accepted.extend(DetectAgent._carve(entity, overlaps))
        return sorted(
            accepted,
            key=lambda item: (item.segment_order, item.start, item.end, item.type.value),
        )

    @staticmethod
    def _carve(entity: Entity, existing: list[Entity]) -> list[Entity]:
        """Вычесть из модельного спана точные, уже принятые сущности правил."""
        intervals = sorted(
            (
                max(entity.start, other.start),
                min(entity.end, other.end),
            )
            for other in existing
            if other.segment_order == entity.segment_order
        )
        fragments: list[tuple[int, int]] = []
        cursor = entity.start
        for start, end in intervals:
            if cursor < start:
                fragments.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < entity.end:
            fragments.append((cursor, entity.end))

        carved: list[Entity] = []
        for start, end in fragments:
            local_start = start - entity.start
            local_end = end - entity.start
            bounds = shrink_span(entity.text, local_start, local_end)
            if bounds is None:
                continue
            local_start, local_end = bounds
            value_start = entity.start + local_start
            value_end = entity.start + local_end
            text = entity.text[local_start:local_end]
            if (
                value_end - value_start < MIN_FRAGMENT_LEN
                or not any(char.isalpha() for char in text)
                or is_organization_form_only(text)
                or is_role_stopword(text)
            ):
                continue
            if value_start != entity.start and not DetectAgent._has_fragment_evidence(
                entity.type, text
            ):
                continue
            carved.append(
                Entity(
                    type=entity.type,
                    text=text,
                    segment_order=entity.segment_order,
                    start=value_start,
                    end=value_end,
                    source=entity.source,
                    confidence=entity.confidence,
                    normalized=normalize_value(entity.type, text),
                )
            )
        return carved

    @staticmethod
    def _has_fragment_evidence(entity_type: EntityType, text: str) -> bool:
        if entity_type is EntityType.ORG_NAME:
            return has_organization_evidence(text)
        if entity_type is not EntityType.PERSON:
            return False
        tokens = [token.strip(".,;:()[]{}«»\"'“”„") for token in text.split()]
        return bool(tokens) and all(
            token
            and (token[0].isupper() or bool(re.fullmatch(r"[А-ЯЁ]\.?", token, flags=re.IGNORECASE)))
            for token in tokens
        )

    def detect(self, document: Document) -> DetectionResult:
        """Запустить детекторы и вернуть проверенный, объединённый результат.

        Сквозной досмотр (``sweep``, план T2.2.2, шаг 8, Д13) — последний
        проход, после разрешения перекрытий: расширяет уже принятые
        значения по всему документу, а не ищет новые типы сущностей.
        """
        found: list[tuple[EntityDetector, Entity]] = []
        for detector in self._detectors:
            entities = detector.detect(document)
            self._validate(detector, document, entities)
            found.extend((detector, entity) for entity in entities)
        entities = self._resolve_overlaps(found)
        entities = sorted(
            [*entities, *sweep(document, entities)],
            key=lambda item: (item.segment_order, item.start, item.end, item.type.value),
        )
        chunks = build_pii_chunks(document.segments, entities)
        return DetectionResult(entities=entities, chunks=chunks)
