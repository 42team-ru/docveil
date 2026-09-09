"""Общий результат DetectAgent и построение контекстных PII-чанков."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from masker.model import Entity, Segment

if TYPE_CHECKING:
    from masker.detect.verifier import VerifierReport

CHUNK_TARGET = 300
CHUNK_MIN = 200
CHUNK_MAX = 500


@dataclass(slots=True)
class PiiChunk:
    """Окрестность одного или нескольких PII в одном сегменте."""

    segment_order: int
    start: int
    end: int
    entities: list[Entity]


@dataclass(slots=True)
class DetectionResult:
    """Принятые сущности и пригодные для контекстных стадий чанки.

    ``verifier`` — сводка LLM-верификатора на recall (Р7), если он вообще
    включался: `None`, когда `DetectAgent` собран без `llm=` (офлайн-путь,
    ``make gate`` и весь остальной корпус тестов без единого сетевого
    вызова). Заполняется `DetectAgent.detect()` результатом
    `masker.detect.verifier.summarize_verdicts` — сюда попадают только
    вердикты и счётчики, а не сами найденные сущности: они уже слиты в
    ``entities`` выше.
    """

    entities: list[Entity]
    chunks: list[PiiChunk]
    verifier: VerifierReport | None = None


def _desired_window(text_length: int, entity: Entity) -> tuple[int, int]:
    """Вернуть ограниченную границами сегмента окрестность сущности."""
    entity_length = entity.end - entity.start
    if text_length <= CHUNK_MIN:
        return 0, text_length
    if entity_length >= CHUNK_TARGET:
        return max(0, entity.start), min(text_length, entity.end)

    window_length = min(CHUNK_TARGET, text_length)
    midpoint = (entity.start + entity.end) // 2
    start = midpoint - window_length // 2
    start = max(0, min(start, text_length - window_length))
    return start, start + window_length


def _deduplicate_entities(entities: list[Entity]) -> list[Entity]:
    seen: set[tuple[int, int, int, object]] = set()
    result: list[Entity] = []
    for entity in sorted(entities, key=lambda item: (item.start, item.end, item.type)):
        key = (entity.segment_order, entity.start, entity.end, entity.type)
        if key not in seen:
            seen.add(key)
            result.append(entity)
    return result


def _merge_neighbouring_chunks(chunks: list[PiiChunk]) -> list[PiiChunk]:
    """Склеить пересёкшиеся после расширения окна, не нарушая лимит."""
    merged: list[PiiChunk] = []
    for chunk in chunks:
        if (
            merged
            and merged[-1].segment_order == chunk.segment_order
            and chunk.start < merged[-1].end
            and max(merged[-1].end, chunk.end) - min(merged[-1].start, chunk.start) <= CHUNK_MAX
        ):
            previous = merged[-1]
            previous.start = min(previous.start, chunk.start)
            previous.end = max(previous.end, chunk.end)
            previous.entities = _deduplicate_entities([*previous.entities, *chunk.entities])
        else:
            merged.append(chunk)
    return merged


def build_pii_chunks(segments: list[Segment], entities: list[Entity]) -> list[PiiChunk]:
    """Сгруппировать принятые PII в непересекающиеся контекстные окна.

    Функция не детектирует и не меняет переданные сегменты или сущности.
    """
    text_by_order = {segment.order: segment.text for segment in segments}
    chunks: list[PiiChunk] = []
    for entity in sorted(entities, key=lambda item: (item.segment_order, item.start, item.end)):
        text = text_by_order[entity.segment_order]
        desired_start, desired_end = _desired_window(len(text), entity)
        if chunks and chunks[-1].segment_order == entity.segment_order:
            current = chunks[-1]
            overlaps_current = entity.start < current.end and current.start < entity.end
            expanded_start = min(current.start, desired_start)
            expanded_end = max(current.end, desired_end)
            if overlaps_current and expanded_end - expanded_start <= CHUNK_MAX:
                current.start = expanded_start
                current.end = expanded_end
                current.entities = _deduplicate_entities([*current.entities, entity])
                continue
        chunks.append(
            PiiChunk(
                segment_order=entity.segment_order,
                start=desired_start,
                end=desired_end,
                entities=[entity],
            )
        )
    return _merge_neighbouring_chunks(chunks)
