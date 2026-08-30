"""Словарь и детектор адресов, собранных из адресных компонентов."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source


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


@dataclass(frozen=True, slots=True)
class _Chunk:
    start: int
    end: int
    kinds: frozenset[str]
    value_start: int


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

    def __init__(self) -> None:
        markers = address_markers()
        self._index = re.compile(markers.index_pattern)
        self._region = _marker_pattern(markers.region)
        self._settlement = _marker_pattern(markers.settlement)
        self._street = _marker_pattern(markers.street)
        self._building = _marker_pattern(markers.building)
        self._premises = _marker_pattern(markers.premises)
        self._value_labels = tuple(label.casefold() for label in markers.value_labels)

    def _chunks(self, text: str) -> list[_Chunk]:
        chunks: list[_Chunk] = []
        previous_kinds: frozenset[str] = frozenset()
        for match in _CHUNK_RE.finditer(text):
            start, end = _trim_bounds(text, match.start(), match.end())
            if start == end:
                continue
            value = text[start:end]
            index = self._index.search(value)
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
            chunks.append(_Chunk(start=start, end=end, kinds=kinds, value_start=value_start))
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
        for segment_index, segment in enumerate(document.segments):
            chunks = self._chunks(segment.text)
            index = 0
            while index < len(chunks):
                first = chunks[index]
                if not first.kinds:
                    index += 1
                    continue
                kinds = set(first.kinds)
                end_index = index
                while end_index + 1 < len(chunks) and chunks[end_index + 1].kinds:
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
                            confidence=0.9 if is_sufficient else 0.5,
                            normalized=normalize_value(EntityType.ADDRESS, value),
                        )
                    )
                    index = end_index + 1
                else:
                    index += 1
        return found
