"""Сквозной досмотр уже запланированных значений по всему документу (Д13, план T2.2.2, шаг 8).

Значение замаскировано в одном месте документа и осталось открытым в
другом — не гипотетический риск, а измеренный дефект: голое
`2025.334807` на стр. 45 (правило `contract_number` контекстное — там, где
рядом нет слова «договор», оно не срабатывает) и `Мокина Светлана
Владимировна`/`Администрации города`, замаскированные в одних сегментах и
оставшиеся открытыми в других (см. диагностику Д13 плана T2.2.2).

``sweep`` не ищет новых *типов* сущностей — он лишь досматривает уже
принятые остальными детекторами значения по всему документу: для каждого
уникального ``(type, text)`` из белого списка типов (только там, где
досмотр оправдан — короткие общие слова вроде «Мармит»/«ТР ТС» рискуют
тиражировать ложное срабатывание, риск Р4 плана) ищутся точные вхождения
на границе слова, не пересекающиеся с уже принятыми сущностями.

Детерминизм — обязательное условие, а не стиль: без явной сортировки два
прогона на одном документе дали бы разные ``ref`` у одинаковых сущностей
(раздел «Детерминизм» плана T2.2.2). Порядок: значения — по ``(тип,
значение)``, сегменты — по ``order``, вхождения внутри сегмента — по
смещению начала.
"""

from __future__ import annotations

import re

from masker.detect.normalize import normalize_value
from masker.model import Document, Entity, EntityType, Source

#: Короче — риск ложного совпадения растёт (единицы измерения, короткие
#: сокращения), длиннее — уже почти наверняка уникальное значение.
MIN_VALUE_LEN = 6

#: Досмотр расширяет только уже принятые значения этих типов — критичные
#: реквизиты и стороны договора. Открытый белый список, а не «всё подряд»:
#: у произвольного типа (`money`, `date`) совпадение по значению почти
#: наверняка случайное (риск Р4 плана T2.2.2).
SWEEP_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.CONTRACT_NUMBER,
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.BIK,
        EntityType.KPP,
        EntityType.BANK_ACCOUNT,
        EntityType.PERSON,
        EntityType.ORG_NAME,
    }
)


def _covered(ranges: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(
        existing_start < end and start < existing_end for existing_start, existing_end in ranges
    )


def sweep(
    document: Document,
    entities: list[Entity],
    extra_types: frozenset[str] = frozenset(),
) -> list[Entity]:
    """Найти непокрытые точные вхождения уже принятых значений (Д13).

    ``entities`` — уже объединённый и разрешённый по перекрытиям результат
    остальных детекторов; сюда не должны попадать сущности самого
    досмотра (вызывающий, ``DetectAgent.detect``, зовёт это последним
    проходом).
    """
    value_confidence: dict[tuple[str, str], float] = {}
    covered_by_segment: dict[int, list[tuple[int, int]]] = {}
    for entity in entities:
        covered_by_segment.setdefault(entity.segment_order, []).append((entity.start, entity.end))
        if entity.type not in SWEEP_TYPES and entity.type not in extra_types:
            continue
        if len(entity.text) < MIN_VALUE_LEN:
            continue
        key = (entity.type, entity.text)
        # Первое встреченное значение выигрывает — `entities` уже
        # детерминированно отсортирован вызывающим (`DetectAgent`).
        value_confidence.setdefault(key, entity.confidence)
        # Нормализованный пробел: «Иванова Светлана  Петровна» (двойной
        # пробел из PDF-потоков) должна найти «Иванова Светлана Петровна»
        # в другом сегменте (Д13, PDF-специфика, вариант пробела).
        collapsed = " ".join(entity.text.split())
        if collapsed != entity.text and len(collapsed) >= MIN_VALUE_LEN:
            value_confidence.setdefault((entity.type, collapsed), entity.confidence)

    segments_by_order = sorted(document.segments, key=lambda segment: segment.order)

    found: list[Entity] = []
    for entity_type, value in sorted(value_confidence, key=lambda item: (item[0], item[1])):
        confidence = value_confidence[(entity_type, value)]
        # Для многословных значений пробелы между словами допускаем гибко:
        # PDF-потоки могут вставлять двойной пробел там, где в DOCX один
        # (Д13, T2.2.2). «\s+» не влияет на ИНН/ОГРН — там нет пробелов.
        words = value.split()
        flexible = r"\s+".join(re.escape(w) for w in words) if len(words) > 1 else re.escape(value)
        pattern = re.compile(rf"(?<!\w){flexible}(?!\w)")
        for segment in segments_by_order:
            ranges = covered_by_segment.setdefault(segment.order, [])
            for match in pattern.finditer(segment.text):
                start, end = match.start(), match.end()
                if _covered(ranges, start, end):
                    continue
                text = segment.text[start:end]
                found.append(
                    Entity(
                        type=entity_type,
                        text=text,
                        segment_order=segment.order,
                        start=start,
                        end=end,
                        source=Source.RULE,
                        confidence=confidence,
                        normalized=normalize_value(entity_type, text),
                    )
                )
                ranges.append((start, end))
    return found
