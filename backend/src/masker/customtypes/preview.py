"""Live preview скомпилированного пользовательского типа (план T1.13, шаг 10).

Никакой синтетики: preview всегда исполняет настоящий executor по настоящим
сегментам документа (design notes T1.13, раздел 2.5 — «отвергнутые
альтернативы»). Выбор показываемых сегментов детерминирован — единственный
источник порядка — обход по возрастанию ``Segment.order``, никакой
«случайной»/«репрезентативной» выборки.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from masker.model import Document, Entity, Segment
from masker.typeconfig import CustomTypeSpec

#: До скольких сегментов показывать (design notes T1.13, раздел 2.5).
DEFAULT_SEGMENT_LIMIT = 3

#: Окно вокруг совпадения, в символах в каждую сторону (план, шаг 7 —
#: тот же формат, что отдаёт REST-схема ``PreviewSegmentOut``).
WINDOW_CHARS = 120

#: Длина окна сегмента без совпадений (типа «ничего не нашлось» — самый
#: ценный сигнал preview, design notes раздел 2.5).
EMPTY_WINDOW_CHARS = 2 * WINDOW_CHARS


@dataclass(frozen=True, slots=True)
class PreviewMatch:
    """Одно совпадение, смещения локальны в ``PreviewSegment.text``."""

    start: int
    end: int
    value: str


@dataclass(frozen=True, slots=True)
class PreviewSegment:
    """Сегмент документа с окном вокруг совпадений (или без них)."""

    segment_order: int
    anchor_label: str
    text: str
    matches: list[PreviewMatch] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PreviewResult:
    """Итог ``preview()``: до ``limit`` сегментов и общее число совпадений в документе."""

    segments: list[PreviewSegment] = field(default_factory=list)
    total_matches: int = 0


def _entities_for_spec(spec: CustomTypeSpec, document: Document) -> list[Entity]:
    """Исполнить executor, соответствующий ``spec.kind``, по всему документу."""
    if spec.kind in ("literals", "regex"):
        from masker.detect.config_detector import ConfigDetector

        return ConfigDetector([spec]).detect(document)
    if spec.kind.startswith("gliner_"):
        from masker.detect.gliner import GlinerDetector

        return GlinerDetector([spec]).detect(document)
    raise ValueError(f"нет executor'а предпросмотра для kind={spec.kind!r}")


def preview(
    spec: CustomTypeSpec, document: Document, *, limit: int = DEFAULT_SEGMENT_LIMIT
) -> PreviewResult:
    """Прогнать ``spec`` по документу и вернуть до ``limit`` сегментов-образцов.

    Сначала сегменты с совпадениями (по возрастанию ``order``, до ``limit``
    штук). Если совпадений нет вовсе — первые ``limit`` непустых сегментов
    документа и ``total_matches == 0``: явный сигнал «ничего не нашлось».
    """
    entities = _entities_for_spec(spec, document)
    total_matches = len(entities)

    by_segment: dict[int, list[Entity]] = {}
    for entity in entities:
        by_segment.setdefault(entity.segment_order, []).append(entity)

    segments_by_order = {segment.order: segment for segment in document.segments}

    if by_segment:
        orders = sorted(by_segment)[:limit]
        preview_segments = [
            _segment_with_matches(segments_by_order[order], by_segment[order]) for order in orders
        ]
    else:
        non_empty = sorted(
            (segment for segment in document.segments if segment.text.strip()),
            key=lambda segment: segment.order,
        )[:limit]
        preview_segments = [_segment_without_matches(segment) for segment in non_empty]

    return PreviewResult(segments=preview_segments, total_matches=total_matches)


def _segment_with_matches(segment: Segment, entities: list[Entity]) -> PreviewSegment:
    ordered = sorted(entities, key=lambda item: (item.start, item.end))
    window_start = max(0, min(item.start for item in ordered) - WINDOW_CHARS)
    window_end = min(len(segment.text), max(item.end for item in ordered) + WINDOW_CHARS)
    text = segment.text[window_start:window_end]
    matches = [
        PreviewMatch(start=item.start - window_start, end=item.end - window_start, value=item.text)
        for item in ordered
    ]
    return PreviewSegment(
        segment_order=segment.order, anchor_label=segment.anchor.label, text=text, matches=matches
    )


def _segment_without_matches(segment: Segment) -> PreviewSegment:
    return PreviewSegment(
        segment_order=segment.order,
        anchor_label=segment.anchor.label,
        text=segment.text[:EMPTY_WINDOW_CHARS],
        matches=[],
    )
