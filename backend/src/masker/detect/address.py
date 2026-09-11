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
# Скобки не разрывают реквизит: в PDF после названия организации в скобках
# сразу идёт «Юридический адрес» (11.09.2026, eat-654000009321.pdf).
# Кавычки оставлены границей: за ними часто начинается номер договора.
_HARD_BOUNDARY_RE: Final = re.compile(r'[;"«»]')
# Точка после коротких «д»/«стр» может не войти в маркер из-за lookahead,
# поэтому принимается и перед значением (11.09.2026, arkhschool-68-183.pdf:
# «д.10, стр.2»). Иначе дом и строение выпадали из единого спана.
_NUMBER_VALUE_RE: Final = re.compile(r"\s*\.?\s*(\d[\w-]*)")
_LETTER_VALUE_RE: Final = re.compile(r"\s*([А-ЯЁ])\b", re.IGNORECASE)
_NAME_VALUE_RE: Final = re.compile(r"\s+([А-ЯЁ][\w-]*(?:\s+[А-ЯЁ][\w-]*)*)")
# Маркер, с которого продолжается адрес, разорванный границей абзаца одной
# ячейки: «309512, ..., г. Старый Оскол,» + «мкр. Жукова, д. 20, кв. 15».
_CONTINUATION_MARKER_RE: Final = re.compile(r"^(?:мкр|ул|д|кв|оф|корп)\.", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Chunk:
    start: int
    end: int
    kinds: frozenset[str]
    value_start: int
    is_stop: bool
    stops_after: bool
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
    suffix = text[match.end() :].lstrip(" \t.")
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
    types: frozenset[str] = frozenset({EntityType.ADDRESS})

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

    @classmethod
    def _address_limit(cls, value: str) -> int:
        """Вернуть допустимую границу поиска внутри чанка адреса."""
        limit = cls._hard_boundary(value)
        # Кавычки до явной метки адреса принадлежат названию организации,
        # а не разделяют реквизиты. Это позволяет начать после них с
        # индекса (11.09.2026, eat-654000009321.pdf); голые числа после
        # кавычки по-прежнему отсекаются прежней защитой выше.
        return len(value) if "адрес" in value.casefold()[limit:] else limit

    def _stop_positions(self, value: str) -> list[int]:
        """Вернуть позиции самостоятельных реквизитов, а не частей слов."""
        positions: list[int] = []
        for label in self._stop_labels:
            pattern = (
                r"(?<!\w)тел(?:\.|ефон\b)"
                if label == "тел"
                else rf"(?<!\w){re.escape(label)}(?!\w)"
            )
            positions.extend(match.start() for match in re.finditer(pattern, value, re.IGNORECASE))
        return positions

    @staticmethod
    def _number_end(value: str, start: int, limit: int) -> int | None:
        match = _NUMBER_VALUE_RE.match(value, start)
        if match is None or match.end(1) > limit:
            return None
        return match.end(1)

    @staticmethod
    def _building_end(value: str, start: int, limit: int, marker: str) -> int | None:
        """Вернуть номер дома либо букву литеры после её маркера."""
        number_end = AddressDetector._number_end(value, start, limit)
        if number_end is not None:
            return number_end
        # Литера бывает самостоятельным адресным компонентом («Литера А»),
        # а не только суффиксом номера. Это зафиксировано 11.09.2026 на
        # eat-654000009321.pdf: требование цифры оставляло «А» открытой.
        if marker.casefold().startswith(("лит", "литера")):
            match = _LETTER_VALUE_RE.match(value, start)
            if match is not None and match.end(1) <= limit:
                return match.end(1)
        return None

    @staticmethod
    def _name_end(value: str, start: int, limit: int) -> int | None:
        match = _NAME_VALUE_RE.match(value, start)
        if match is None:
            return None
        return min(match.end(1), limit)

    @staticmethod
    def _postfix_street_start(value: str, pattern: re.Pattern[str], limit: int) -> int | None:
        """Найти улицу с маркером после названия: «Пресненская наб.»."""
        marker = pattern.search(value)
        if marker is None or marker.start() >= limit:
            return None
        prefix = value[: marker.start()].strip()
        return 0 if re.search(r"[А-ЯЁа-яё]", prefix) is not None else None

    def _component_end(
        self,
        value: str,
        *,
        index: re.Match[str] | None,
        kinds: frozenset[str],
        previous_kinds: frozenset[str],
    ) -> int:
        """Вернуть конец последнего значения компонента, не всего чанка."""
        limit = self._address_limit(value)
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
            for marker in pattern.finditer(value):
                if kind not in kinds:
                    continue
                number_end = (
                    self._building_end(value, marker.end(), limit, marker.group())
                    if kind == "building"
                    else self._number_end(value, marker.end(), limit)
                )
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
            folded = value.casefold()
            first_stop = min(self._stop_positions(value), default=None)
            has_index_like = bool(re.search(r"\d{6}", value))
            # Ничего после «жёсткой» границы (кавычка, скобка, перенос строки)
            # не считается маркером адреса вовсе — иначе `value_start` может
            # уйти за маркер, найденный только там (например, случайное
            # 6-значное совпадение с индексом внутри номера договора после
            # открывающей кавычки), а `_component_end` его туда не пустит:
            # получился бы `end < start` и падение в `DetectAgent._validate`
            # (найдено на реальном PDF-блоке после шага 8 плана T2.2.1).
            limit = self._address_limit(value)
            index = self._index.search(value)
            if index is not None and index.end() > limit:
                index = None
            region_start = _marker_start(value, self._region)
            if region_start is not None and region_start >= limit:
                region_start = None
            settlement_start = _marker_start(value, self._settlement, requires_name=True)
            if settlement_start is not None and settlement_start >= limit:
                settlement_start = None
            street_start = _marker_start(value, self._street, requires_name=True)
            if street_start is None:
                street_start = self._postfix_street_start(value, self._street, limit)
            if street_start is not None and street_start >= limit:
                street_start = None
            building_start = _marker_start(value, self._building, requires_number=True)
            if building_start is None:
                building_marker = self._building.search(value)
                if (
                    building_marker is not None
                    and building_marker.start() < limit
                    and self._building_end(
                        value, building_marker.end(), limit, building_marker.group()
                    )
                    is not None
                ):
                    building_start = building_marker.start()
            if building_start is not None and building_start >= limit:
                building_start = None
            premises_start = _marker_start(value, self._premises, requires_number=True)
            if premises_start is not None and premises_start >= limit:
                premises_start = None
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
            # Метка ИНН или банка может оказаться в том же текстовом чанке,
            # что и «д. 14 Литера А». В таком случае чанк нужен, а его конец
            # уже точно режет `_component_end` (11.09.2026,
            # eat-654000009321.pdf); останавливаемся только до следующего
            # самостоятельного реквизита.
            address_start = folded.find("адрес")
            marker_starts = tuple(
                marker_start
                for marker_start in (
                    index.start() if index is not None else None,
                    region_start,
                    settlement_start,
                    street_start,
                    building_start,
                    premises_start,
                )
                if marker_start is not None
            )
            # В PDF один сегмент иногда склеивает название учреждения с его
            # реквизитами: «Республики Башкортостан ... юридический адрес:
            # 450008». Маркер региона из названия не открывает адрес. Если
            # после метки «адрес» есть свой адресный компонент, именно он
            # задаёт начало нового реквизита; иначе метка остаётся стопом для
            # предыдущего адреса.
            address_label = re.search(r"адрес\s*:", folded)
            markers_after_address = (
                tuple(start for start in marker_starts if start >= address_label.end())
                if address_label is not None
                and region_start is not None
                and region_start < address_label.start()
                else ()
            )
            first_marker = min(markers_after_address or marker_starts, default=None)
            is_stop = (has_index_like and not kinds) or (
                first_stop is not None and (first_marker is None or first_stop < first_marker)
            ) or (address_start >= 0 and first_marker is None)
            stop_offsets = [
                offset
                for offset in (first_stop, address_start)
                if first_marker is not None and offset is not None and offset > first_marker
            ]
            stop_after = min(stop_offsets, default=None)
            stops_after = stop_after is not None
            # Следующая метка адреса открывает новый реквизит, а не продолжает
            # предыдущий: без этого в arkhschool-68-183.pdf 11.09.2026 после
            # «д. 30 стр.1» захватывался «Почтовый адрес» из соседней колонки.
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
                value[:stop_after] if stop_after is not None else value,
                index=index,
                kinds=kinds,
                previous_kinds=previous_kinds,
            )
            # Инвариант, а не оптимистичное допущение: конец компонента не
            # имеет права оказаться раньше его начала — `Entity`/`_Chunk` с
            # `end < start` роняет `DetectAgent._validate` (см. комментарий
            # у `limit` выше).
            value_end = max(value_end, value_start)
            chunks.append(
                _Chunk(
                    start=start,
                    end=value_end,
                    kinds=kinds,
                    value_start=value_start,
                    is_stop=is_stop,
                    stops_after=stops_after,
                    has_hard_boundary=self._address_limit(value) < len(value),
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

    def _link_paragraph_split(self, document: Document, found: list[Entity]) -> None:
        """Дать одинаковый ``normalized`` двум частям адреса, разорванного абзацем.

        Склеить спаны нельзя: смещения ``Entity`` локальны сегменту по контракту
        ``model.py``. Поэтому склеивается ключ — тогда последующий шаг сборки
        маркеров (T1.6) выдаст на обе части один и тот же маркер.
        """
        by_segment: dict[int, list[Entity]] = {}
        for entity in found:
            by_segment.setdefault(entity.segment_order, []).append(entity)
        segments = sorted(document.segments, key=lambda item: item.order)
        texts = {segment.order: segment.text for segment in segments}
        for position in range(1, len(segments)):
            previous_segment = segments[position - 1]
            current_segment = segments[position]
            if not self._same_context(previous_segment, current_segment):
                continue
            previous_entities = by_segment.get(previous_segment.order, [])
            current_entities = by_segment.get(current_segment.order, [])
            if not previous_entities or not current_entities:
                continue
            tail = previous_entities[-1]
            head = current_entities[0]
            remainder = texts[previous_segment.order][tail.end :].strip()
            if not remainder.startswith(","):
                continue
            head_text = texts[current_segment.order][head.start :]
            if not _CONTINUATION_MARKER_RE.match(head_text):
                continue
            merged = f"{tail.normalized} {head.normalized}"
            tail.normalized = merged
            head.normalized = merged

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
                # Адресный компонент может не иметь собственного маркера:
                # «Российская Федерация» и «вн.тер. г. муниципальный округ».
                # Между ними разрешаем переносы строк (11.09.2026,
                # arkhschool-68-183.pdf и eat-654000009321.pdf), но обрываем
                # сборку на реквизите из соседней колонки таблицы.
                while (
                    end_index + 1 < len(chunks)
                    and not chunks[end_index].has_hard_boundary
                    and not chunks[end_index].stops_after
                    and not chunks[end_index + 1].is_stop
                    and not (
                        "index" in chunks[end_index + 1].kinds
                        and "index" in kinds
                        and not chunks[end_index + 1].stops_after
                    )
                ):
                    end_index += 1
                    kinds.update(chunks[end_index].kinds)
                is_sufficient = self._is_sufficient(frozenset(kinds))
                # Немаркированные куски нужны только как мост между
                # компонентами адреса. Их нельзя включать в конец: после
                # «стр.2» в arkhschool-68-183.pdf 11.09.2026 извлечение PDF
                # склеивает левую колонку с «Межрегиональное УФК» справа.
                last_component_index = next(
                    position
                    for position in range(end_index, index - 1, -1)
                    if chunks[position].kinds
                )
                start, end = _trim_bounds(
                    segment.text, first.value_start, chunks[last_component_index].end
                )
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
        self._link_paragraph_split(document, found)
        self._propagate_to_occurrences(document, found)
        return found

    @staticmethod
    def _propagate_to_occurrences(document: Document, found: list[Entity]) -> None:
        """Добавить сущности для всех вхождений уже найденного текста адреса.

        Если детектор нашёл «г. Воронеж» в сегменте 4, а в сегменте 5 оно
        же встречается как часть датостроки («г. Воронеж, 15 января 2026 г.»),
        маска обязана покрыть оба вхождения — иначе ValidateAgent найдёт
        утечку в том сегменте, где детектор промолчал.
        """
        covered_by_seg: dict[int, list[tuple[int, int]]] = {}
        for entity in found:
            covered_by_seg.setdefault(entity.segment_order, []).append((entity.start, entity.end))

        def _overlaps_any(seg_order: int, start: int, end: int) -> bool:
            return any(s < end and start < e for s, e in covered_by_seg.get(seg_order, []))

        existing_texts: set[str] = {e.text for e in found}
        for segment in document.segments:
            for addr_text in existing_texts:
                search_start = 0
                while True:
                    pos = segment.text.find(addr_text, search_start)
                    if pos == -1:
                        break
                    end = pos + len(addr_text)
                    if not _overlaps_any(segment.order, pos, end):
                        found.append(
                            Entity(
                                type=EntityType.ADDRESS,
                                text=addr_text,
                                segment_order=segment.order,
                                start=pos,
                                end=end,
                                source=Source.RULE,
                                confidence=0.7,
                                normalized=normalize_value(EntityType.ADDRESS, addr_text),
                            )
                        )
                        covered_by_seg.setdefault(segment.order, []).append((pos, end))
                    search_start = pos + 1
