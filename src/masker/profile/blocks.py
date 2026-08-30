"""Контекстные блоки для структурного профилирования."""

from __future__ import annotations

import re
from dataclasses import dataclass

from masker.model import Entity, Segment
from masker.profile.labels import find_labels

MAX_EMPTY_GAP = 2
MAX_BLOCK_SPANS = 12
MAX_BLOCK_CHARS = 4000
HEADING = re.compile(r"^\s*\d+(?:\.\d+)*\.?\s+")


@dataclass(frozen=True, slots=True)
class BlockSpan:
    segment_order: int
    start: int
    end: int


@dataclass(slots=True)
class ContextBlock:
    id: str
    spans: list[BlockSpan]
    entities: list[Entity]
    label: str = ""
    heading: str = ""


def _anchor_kind(segment: Segment) -> str:
    return str(segment.anchor.locator[0]) if segment.anchor.locator else ""


def _is_heading(text: str) -> bool:
    stripped = text.strip()
    return bool(HEADING.match(stripped)) or (
        bool(stripped)
        and len(stripped) <= 80
        and ":" not in stripped
        and not stripped.endswith(".")
    )


def _known_label(label: str, labels: set[str]) -> str:
    """Связать падежную форму с уже названной документом ролью без словаря ролей."""
    for known in sorted(labels):
        stem = min(len(label), len(known), 5)
        if label[:stem] == known[:stem]:
            return known
    return label


def build_context_blocks(segments: list[Segment], entities: list[Entity]) -> list[ContextBlock]:
    """Собрать непрерывные блоки; каждая принятая сущность входит ровно в один."""
    entities_by_segment: dict[int, list[Entity]] = {}
    for entity in sorted(entities, key=lambda item: (item.segment_order, item.start, item.end)):
        entities_by_segment.setdefault(entity.segment_order, []).append(entity)
    blocks: list[ContextBlock] = []
    current: ContextBlock | None = None
    active_label = ""
    # Метка, поставленная самим заголовком («1. Реквизиты Исполнителя»), должна
    # управлять всем разделом до следующего заголовка независимо от смены типа
    # якоря внутри раздела (таблица реквизитов идёт сразу после заголовка).
    # Метка, подхваченная из формулировки внутри абзаца (преамбула «именуемое
    # в дальнейшем ...»), такой гарантии не даёт и гасится на первой же смене
    # структуры — иначе она утекает в совсем другой раздел документа.
    active_label_from_heading = False
    seen_labels: set[str] = set()
    empty_gap = 0
    previous_anchor_kind: str | None = None
    for segment in sorted(segments, key=lambda item: item.order):
        segment_anchor_kind = _anchor_kind(segment)
        is_numbered_heading = bool(HEADING.match(segment.text.strip()))
        # Сброс выполняется до применения explicit_label этого же сегмента —
        # иначе заголовок, который сам несёт метку, погасил бы её же.
        if is_numbered_heading or (
            previous_anchor_kind is not None
            and segment_anchor_kind != previous_anchor_kind
            and not active_label_from_heading
        ):
            active_label = ""
            active_label_from_heading = False
        previous_anchor_kind = segment_anchor_kind
        labels = find_labels(segment.text)
        explicit_label = labels[0][1] if labels else ""
        if explicit_label:
            explicit_label = _known_label(explicit_label, seen_labels)
            seen_labels.add(explicit_label)
            active_label = explicit_label
            active_label_from_heading = is_numbered_heading
        heading = segment.text.strip() if _is_heading(segment.text) else ""
        segment_entities = entities_by_segment.get(segment.order, [])
        new_block = current is None
        if current is not None:
            prior_kind = _anchor_kind(
                next(item for item in segments if item.order == current.spans[-1].segment_order)
            )
            new_block = (
                bool(explicit_label and explicit_label != current.label)
                or _anchor_kind(segment) != prior_kind
                or len(current.spans) >= MAX_BLOCK_SPANS
                or sum(span.end - span.start for span in current.spans) + len(segment.text)
                > MAX_BLOCK_CHARS
                or bool(heading and current.entities)
                or bool(segment_entities and empty_gap > MAX_EMPTY_GAP)
            )
        if new_block:
            current = ContextBlock(
                id=f"B{len(blocks) + 1}",
                spans=[],
                entities=[],
                label=active_label,
                heading=heading,
            )
            blocks.append(current)
        assert current is not None
        # Метка блока всегда следует за текущей активной меткой, а не только
        # заполняет пустое поле: иначе блок, начавшийся без сущностей на
        # сегменте с меткой (например, преамбула), донесёт эту метку до
        # сегмента с сущностью даже после того, как метка уже погашена
        # заголовком — граница блока по заголовку срабатывает только когда в
        # блоке уже есть хотя бы одна сущность.
        current.label = active_label
        if heading and not current.heading:
            current.heading = heading
        current.spans.append(BlockSpan(segment.order, 0, len(segment.text)))
        current.entities.extend(segment_entities)
        empty_gap = empty_gap + 1 if not segment_entities else 0
    return blocks


def block_text(segments: list[Segment], block: ContextBlock) -> str:
    """Вернуть текст блока в порядке сегментов и спанов."""
    texts = {segment.order: segment.text for segment in segments}
    return "\n".join(texts[span.segment_order][span.start : span.end] for span in block.spans)
