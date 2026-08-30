"""Оркестрация подключаемых детекторов PII."""

from __future__ import annotations

from collections.abc import Iterable

from masker.detect.base import EntityDetector
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.model import Document, Entity, EntityType, Source


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
            from masker.detect.rules import RuleDetector

            detectors = [RuleDetector()]
        self._detectors = list(detectors)

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
        for _, entity in ordered:
            if not any(_overlaps(entity, existing) for existing in accepted):
                accepted.append(entity)
        return sorted(
            accepted,
            key=lambda item: (item.segment_order, item.start, item.end, item.type.value),
        )

    def detect(self, document: Document) -> DetectionResult:
        """Запустить детекторы и вернуть проверенный, объединённый результат."""
        found: list[tuple[EntityDetector, Entity]] = []
        for detector in self._detectors:
            entities = detector.detect(document)
            self._validate(detector, document, entities)
            found.extend((detector, entity) for entity in entities)
        entities = self._resolve_overlaps(found)
        chunks = build_pii_chunks(document.segments, entities)
        return DetectionResult(entities=entities, chunks=chunks)
