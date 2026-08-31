"""Проверка PII-кандидатов, предложенных моделью."""

from __future__ import annotations

from collections.abc import Iterable

from masker.model import Entity, EntityType, Segment, Source


def build_candidates(
    raw_candidates: Iterable[dict[str, object]], segments: list[Segment], known: list[Entity]
) -> list[Entity]:
    """Принять только дословные, непересекающиеся кандидаты из существующих сегментов."""
    by_order = {segment.order: segment for segment in segments}
    accepted: list[Entity] = []
    for item in raw_candidates:
        try:
            order_value = item["segment_order"]
            confidence_value = item.get("confidence", 0.6)
            if not isinstance(order_value, (int, str)) or not isinstance(
                confidence_value, (int, float, str)
            ):
                continue
            order = int(order_value)
            text = str(item["text"])
            entity_type = EntityType(str(item["type"]))
            segment = by_order[order]
        except (KeyError, TypeError, ValueError):
            continue
        start = segment.text.find(text)
        if not text or start < 0:
            continue
        end = start + len(text)
        overlaps = [*known, *accepted]
        if any(
            entity.segment_order == order and start < entity.end and entity.start < end
            for entity in overlaps
        ):
            continue
        accepted.append(
            Entity(
                type=entity_type,
                text=text,
                segment_order=order,
                start=start,
                end=end,
                source=Source.LLM,
                confidence=min(float(confidence_value), 0.6),
            )
        )
    return sorted(
        accepted,
        key=lambda entity: (entity.segment_order, entity.start, entity.end, entity.type.value),
    )
