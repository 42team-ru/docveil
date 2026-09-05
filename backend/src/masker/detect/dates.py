"""Детектор календарных дат — тип `date` и `birth_date` (план T1.15).

Одна проходка по тексту находит все календарные даты сразу; каждый спан
классифицируется однократно: если рядом с датой стоит триггер рождения —
тип `birth_date`, иначе `date`. Пересечений между этими двумя типами по
построению не бывает.

`date` **не** попадает в `CRITICAL_TYPES`: иначе судья молча замаскирует
дату подписания, сроки поставки и оплаты, и обезличенный договор перестанет
быть договором, по которому можно работать (`docs/plans/T1.15-dates.md`,
раздел «Граница»). Тест-сторож `test_date_is_not_critical` следит за этим
инвариантом.
"""

from __future__ import annotations

import re

from masker.detect.dateparse import (
    MAX_YEAR,
    MIN_YEAR,
    month_number,
    parse_date,
    parse_literal,
)
from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Segment, Source

CONFIDENCE = 0.9

#: Триггеры «дата рождения» справа от даты (вплотную, зазор ≤ 3 символа):
#: «года рождения», «г.р.», «г. р.», «р.». Ловим по началу фразы после даты,
#: не как отдельные слова где-нибудь дальше в предложении.
_RIGHT_BIRTH_TRIGGERS = (
    "года рождения",
    "г.р.",
    "г. р.",
    "г.р",
    "г. р",
    "р.",
)
#: Отсортированы длинными первыми: `"г.р."` должно матчиться раньше `"р."`,
#: иначе на строке `«… 14.10.1986 г.р.»` короткий триггер съедает решение.
_RIGHT_BIRTH_TRIGGERS_ORDERED = tuple(sorted(_RIGHT_BIRTH_TRIGGERS, key=len, reverse=True))
_LONGEST_RIGHT_TRIGGER = max(len(t) for t in _RIGHT_BIRTH_TRIGGERS)
_RIGHT_GAP = 3

#: Триггеры «дата рождения» слева от даты, в окне 40 символов до её начала.
#: Регистр не важен — сравниваем по casefold.
_LEFT_BIRTH_PATTERNS = re.compile(
    r"(?:дата\s+рождени|дата\s+рожд|д\.р\.|род\.|рожд[её]н|рождения)",
    flags=re.IGNORECASE,
)
_LEFT_WINDOW = 40

#: Регулярка ловит числовые формы `dd.mm.yyyy`, `dd/mm/yyyy` и `yyyy-mm-dd`.
#: Двузначные годы не берём (план T1.15, раздел «Не ловим»): выигрыш мал,
#: коллизий с накладными и сериями паспорта много.
_NUMERIC_PATTERN = re.compile(
    r"(?<![\d.])"  # слева не цифра/точка — иначе `1.14.10.1986` даст `14.10.1986`
    r"(?:"
    r"(\d{1,2})[./](\d{1,2})[./](\d{4})"  # dd.mm.yyyy или dd/mm/yyyy
    r"|"
    r"(\d{4})-(\d{1,2})-(\d{1,2})"  # yyyy-mm-dd
    r")"
    r"(?!\d)"
)

#: Текстовая форма: день (цифры или в кавычках) + месяц словом + год.
#: Кавычки вокруг дня входят в спан, чтобы после маскирования не оставалось
#: висящей `»` (план T1.15).
_MONTH_ALTERNATION = (
    r"январ[ья]|феврал[ья]|март[а]?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|"
    r"август[а]?|сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья]"
)
_TEXTUAL_PATTERN = re.compile(
    r"(?<![\w])"
    r"(«?\d{1,2}»?)\s+"  # день (опционально в кавычках)
    rf"({_MONTH_ALTERNATION})\s+"  # месяц словом
    r"(\d{4})"  # год
    r"(?!\d)",
    flags=re.IGNORECASE,
)


class DateDetector:
    """Календарные даты в тексте документа.

    Единственный детектор, отвечающий за оба типа `date` и `birth_date`:
    их спаны не пересекаются по построению (классификация внутри одной
    проходки), поэтому разбивать их на два детектора смысла нет.
    """

    name = "dates"
    source = Source.RULE
    priority = 95
    types: frozenset[str] = frozenset({EntityType.DATE, EntityType.BIRTH_DATE})

    def detect(self, document: Document) -> list[Entity]:
        entities: list[Entity] = []
        for segment in document.segments:
            entities.extend(self._detect_segment(segment))
        return sorted(
            entities, key=lambda item: (item.segment_order, item.start, item.end, item.type)
        )

    def _detect_segment(self, segment: Segment) -> list[Entity]:
        text = segment.text
        found: list[tuple[int, int, str]] = []

        for match in _NUMERIC_PATTERN.finditer(text):
            if match.group(1) is not None:
                # dd.mm.yyyy или dd/mm/yyyy
                day, month, year = match.group(1), match.group(2), match.group(3)
            else:
                # yyyy-mm-dd
                year, month, day = match.group(4), match.group(5), match.group(6)
            if parse_date(int(day), int(month), int(year)) is None:
                continue
            found.append((match.start(), match.end(), match.group(0)))

        for match in _TEXTUAL_PATTERN.finditer(text):
            day_token = match.group(1).strip("«»\"'“”„")
            month_num = month_number(match.group(2))
            year_token = match.group(3)
            if month_num is None:
                continue
            try:
                day = int(day_token)
                year = int(year_token)
            except ValueError:
                continue
            if parse_date(day, month_num, year) is None:
                continue
            found.append((match.start(), match.end(), match.group(0)))

        found = _drop_overlaps(found)

        entities: list[Entity] = []
        for start, end, value in found:
            entity_type = self._classify(text, start, end)
            entities.append(
                Entity(
                    type=entity_type,
                    text=value,
                    segment_order=segment.order,
                    start=start,
                    end=end,
                    source=Source.RULE,
                    confidence=CONFIDENCE,
                    normalized=normalize_value(entity_type, value),
                )
            )
        return entities

    def _classify(self, text: str, start: int, end: int) -> str:
        """`birth_date`, если рядом с датой есть триггер рождения — иначе `date`."""
        # Правое окно: разделитель (пробел, запятая) ≤ _RIGHT_GAP символов,
        # затем — одна из фраз триггера. Триггеры сортируем длинными первыми,
        # чтобы «г.р.» не проглотилось коротким «р.».
        right_tail = text[end : end + _RIGHT_GAP + _LONGEST_RIGHT_TRIGGER]
        stripped_right = right_tail.lstrip(" \t\xa0,;")
        gap = len(right_tail) - len(stripped_right)
        if gap <= _RIGHT_GAP:
            low = stripped_right.lower()
            for trigger in _RIGHT_BIRTH_TRIGGERS_ORDERED:
                if low.startswith(trigger):
                    return EntityType.BIRTH_DATE

        # Левое окно: фраза-триггер в 40 символах слева от даты.
        left = text[max(0, start - _LEFT_WINDOW) : start]
        if _LEFT_BIRTH_PATTERNS.search(left):
            return EntityType.BIRTH_DATE

        return EntityType.DATE


def _drop_overlaps(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Оставить самый длинный спан на пересечении: детерминированный выбор."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, value in ordered:
        if start < last_end:
            continue
        kept.append((start, end, value))
        last_end = end
    return kept


# Импорт неиспользованных выше символов — для внешних потребителей нормализации.
__all__ = ["MAX_YEAR", "MIN_YEAR", "DateDetector", "parse_literal"]
