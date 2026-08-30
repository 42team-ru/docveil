"""Словарь и детектор адресов, собранных из адресных компонентов."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

import yaml


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
