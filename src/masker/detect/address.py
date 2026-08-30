"""Словарь и детектор адресов, собранных из адресных компонентов."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source

if TYPE_CHECKING:
    from masker.detect.ner import NerTagger


@dataclass(frozen=True, slots=True)
class AddressMarkers:
    """Неизменяемые маркеры компонентов адреса."""

    index_pattern: str
    region: tuple[str, ...]
    settlement: tuple[str, ...]
    street: tuple[str, ...]
    building: tuple[str, ...]
    premises: tuple[str, ...]
    value_labels: tuple[str, ...]
    stop_labels: tuple[str, ...]


def _sorted(values: list[str]) -> tuple[str, ...]:
    return tuple(sorted(values, key=lambda value: (-len(value), value.casefold())))


@functools.lru_cache(maxsize=1)
def address_markers() -> AddressMarkers:
    """Прочитать словарь маркеров один раз за процесс."""
    path = Path(__file__).with_name("data") / "address_markers.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AddressMarkers(
        index_pattern=raw["index_pattern"],
        region=_sorted(raw["region"]),
        settlement=_sorted(raw["settlement"]),
        street=_sorted(raw["street"]),
        building=_sorted(raw["building"]),
        premises=_sorted(raw["premises"]),
        value_labels=_sorted(raw["value_labels"]),
        stop_labels=_sorted(raw["stop_labels"]),
    )


_CHUNK_RE: Final = re.compile(r"[^,;]+")
_TRIM_CHARS: Final = " \t\u00a0.,;:"
_HARD_BOUNDARY_RE: Final = re.compile(r'[();"«»\n]')
_NUMBER_VALUE_RE: Final = re.compile(r"\s*(\d[\w-]*)")
_NAME_VALUE_RE: Final = re.compile(r"\s+([А-ЯЁ][\w-]*(?:\s+[А-ЯЁ][\w-]*)*)")


@dataclass(frozen=True, slots=True)
class _Chunk:
    start: int
    end: int
    kinds: frozenset[str]
    value_start: int
    is_stop: bool
    has_hard_boundary: bool


def _marker_pattern(values: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(value) for value in values)
    return re.compile(rf"(?<!\w)(?:{alternatives})\.?(?!\w)", re.IGNORECASE)


def _marker_start(
    text: str,
    pattern: re.Pattern[str],
    *,
    requires_name: bool = False,
    requires_number: bool = False,
) -> int | None:
    match = pattern.search(text)
    if match is None:
        return None
    suffix = text[match.end() :].lstrip()
    if requires_name and (not suffix or not suffix[0].isupper()):
        return None
    if requires_number and (not suffix or not suffix[0].isdigit()):
        return None
    return match.start()


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start] in _TRIM_CHARS:
        start += 1
    while start < end and text[end - 1] in _TRIM_CHARS:
        end -= 1
    return start, end


class AddressDetector:
    """Собрать адрес из индексa, населённого пункта и адресных маркеров."""

    name = "address"
    source = Source.RULE
    priority = 90
    types = frozenset({EntityType.ADDRESS})

    def __init__(self, tagger: NerTagger | None = None) -> None:
        markers = address_markers()
        self._index = re.compile(markers.index_pattern)
        self._region = _marker_pattern(markers.region)
        self._settlement = _marker_pattern(markers.settlement)
        self._street = _marker_pattern(markers.street)
        self._building = _marker_pattern(markers.building)
        self._premises = _marker_pattern(markers.premises)
        self._value_labels = tuple(label.casefold() for label in markers.value_labels)
        self._stop_labels = tuple(label.casefold() for label in markers.stop_labels)
        self._tagger = tagger

    @staticmethod
    def _hard_boundary(value: str) -> int:
        match = _HARD_BOUNDARY_RE.search(value)
        return match.start() if match is not None else len(value)

    @staticmethod
    def _number_end(value: str, start: int, limit: int) -> int | None:
        match = _NUMBER_VALUE_RE.match(value, start)
        if match is None or match.end(1) > limit:
            return None
        return match.end(1)

    @staticmethod
    def _name_end(value: str, start: int, limit: int) -> int | None:
        match = _NAME_VALUE_RE.match(value, start)
        if match is None:
            return None
        return min(match.end(1), limit)

    def _component_end(
        self,
        value: str,
        *,
        index: re.Match[str] | None,
        kinds: frozenset[str],
        previous_kinds: frozenset[str],
    ) -> int:
        """Вернуть конец последнего значения компонента, не всего чанка."""
        limit = self._hard_boundary(value)
        ends: list[int] = []
        if index is not None and index.end() <= limit:
            ends.append(index.end())
        region = self._region.search(value)
        if region is not None and region.end() <= limit and "region" in kinds:
            ends.append(region.end())
        for kind, pattern in (("settlement", self._settlement), ("street", self._street)):
            marker = pattern.search(value)
            if marker is not None and kind in kinds:
                name_end = self._name_end(value, marker.end(), limit)
                if name_end is not None:
                    ends.append(name_end)
        for kind, pattern in (("building", self._building), ("premises", self._premises)):
            marker = pattern.search(value)
            if marker is not None and kind in kinds:
                number_end = self._number_end(value, marker.end(), limit)
                if number_end is not None:
                    ends.append(number_end)
        if "building" in kinds and "street" in previous_kinds:
            number_end = self._number_end(value, 0, limit)
            if number_end is not None:
                ends.append(number_end)
        return max(ends, default=limit)

    def _chunks(self, text: str) -> list[_Chunk]:
        chunks: list[_Chunk] = []
        previous_kinds: frozenset[str] = frozenset()
        for match in _CHUNK_RE.finditer(text):
            start, end = _trim_bounds(text, match.start(), match.end())
            if start == end:
                continue
            value = text[start:end]
            is_stop = any(label in value.casefold() for label in self._stop_labels) or bool(
                re.search(r"\d{6}", value)
            )
            index = self._index.search(value)
            if index is not None:
                is_stop = False
            region_start = _marker_start(value, self._region)
            settlement_start = _marker_start(value, self._settlement, requires_name=True)
            street_start = _marker_start(value, self._street, requires_name=True)
            building_start = _marker_start(value, self._building, requires_number=True)
            premises_start = _marker_start(value, self._premises, requires_number=True)
            kinds = frozenset(
                kind
                for kind, marker_start in (
                    ("index", index.start() if index is not None else None),
                    ("region", region_start),
                    ("settlement", settlement_start),
                    ("street", street_start),
                    ("building", building_start),
                    ("premises", premises_start),
                )
                if marker_start is not None
            )
            if not kinds and "street" in previous_kinds and re.match(r"\d", value):
                kinds = frozenset({"building"})
                building_start = 0
            starts = [
                marker_start
                for marker_start in (
                    index.start() if index is not None else None,
                    settlement_start,
                    street_start,
                    building_start,
                    premises_start,
                )
                if marker_start is not None
            ]
            value_start = start + (min(starts) if starts else 0)
            value_end = start + self._component_end(
                value,
                index=index,
                kinds=kinds,
                previous_kinds=previous_kinds,
            )
            chunks.append(
                _Chunk(
                    start=start,
                    end=value_end,
                    kinds=kinds,
                    value_start=value_start,
                    is_stop=is_stop,
                    has_hard_boundary=self._hard_boundary(value) < len(value),
                )
            )
            previous_kinds = kinds
        return chunks

    @staticmethod
    def _is_sufficient(kinds: frozenset[str]) -> bool:
        return "index" in kinds or (
            "settlement" in kinds and ("street" in kinds or "building" in kinds)
        )

    def _has_value_label(self, document: Document, segment_index: int, start: int) -> bool:
        segment = document.segments[segment_index]
        prefix = segment.text[max(0, start - 60) : start].casefold()
        if any(label in prefix for label in self._value_labels):
            return True
        for previous_index in range(max(0, segment_index - 2), segment_index):
            previous = document.segments[previous_index]
            if not self._same_context(previous, segment):
                continue
            value = previous.text.strip()
            if value.endswith(":") and any(
                label in value.casefold() for label in self._value_labels
            ):
                return True
        return False

    @staticmethod
    def _same_context(previous: Segment, current: Segment) -> bool:
        if previous.anchor.fmt != current.anchor.fmt:
            return False
        previous_locator = previous.anchor.locator
        current_locator = current.anchor.locator
        if previous_locator[0] == current_locator[0] == "body":
            return True
        return bool(
            previous_locator[0] == current_locator[0] == "table"
            and previous_locator[:4] == current_locator[:4]
        )

    def detect(self, document: Document) -> list[Entity]:
        """Найти достаточные для маскирования адреса в каждом сегменте."""
        found: list[Entity] = []
        loc_spans = (
            {
                segment.order: [
                    (span.start, span.end)
                    for span in self._tagger.spans(segment.text)
                    if span.label == "LOC"
                ]
                for segment in document.segments
            }
            if self._tagger is not None
            else {}
        )
        for segment_index, segment in enumerate(document.segments):
            chunks = self._chunks(segment.text)
            index = 0
            while index < len(chunks):
                first = chunks[index]
                if first.is_stop or not first.kinds:
                    index += 1
                    continue
                kinds = set(first.kinds)
                end_index = index
                while (
                    end_index + 1 < len(chunks)
                    and not chunks[end_index].has_hard_boundary
                    and not chunks[end_index + 1].is_stop
                    and chunks[end_index + 1].kinds
                ):
                    end_index += 1
                    kinds.update(chunks[end_index].kinds)
                is_sufficient = self._is_sufficient(frozenset(kinds))
                start, end = _trim_bounds(segment.text, first.value_start, chunks[end_index].end)
                if is_sufficient or self._has_value_label(document, segment_index, start):
                    value = segment.text[start:end]
                    found.append(
                        Entity(
                            type=EntityType.ADDRESS,
                            text=value,
                            segment_order=segment.order,
                            start=start,
                            end=end,
                            source=Source.RULE,
                            confidence=(
                                0.9
                                if is_sufficient
                                else 0.7
                                if any(
                                    start <= loc_start and loc_end <= end
                                    for loc_start, loc_end in loc_spans.get(segment.order, [])
                                )
                                else 0.5
                            ),
                            normalized=normalize_value(EntityType.ADDRESS, value),
                        )
                    )
                    index = end_index + 1
                else:
                    index += 1
        return found
