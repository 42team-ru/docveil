"""Фильтр ложных PERSON по частоте повторения в одном документе (Р15).

Одна и та же роль стороны может встречаться на каждой странице договора.
Если несколько слоёв детекции принимают такое однословное нарицательное за
``person``, план маскирования превращает одну ошибку в сотни замен. В отличие
от списка известных ролей этот признак переносится на незнакомые виды договоров.
"""

from __future__ import annotations

from collections import defaultdict

from masker.detect.morph import has_name_grammeme
from masker.detect.normalize import normalize_value
from masker.detect.orgforms import TRIM_CHARS
from masker.model import Entity, EntityType

# Шесть повторов фамилии Бугакина есть в настоящем договоре. Порог выше неё
# с запасом в одно упоминание: имя, увиденное до семи раз, этот фильтр не
# затрагивает; 96 повторов роли стороны уверенно попадают под правило.
_COMMON_NOUN_PERSON_MIN_OCCURRENCES = 8


def _single_common_noun(entity: Entity) -> bool:
    """Проверить, что кандидат — однословное нарицательное, не ФИО."""
    tokens = entity.text.strip(TRIM_CHARS).split()
    return len(tokens) == 1 and not has_name_grammeme(tokens[0])


def drop_frequent_common_noun_persons(entities: list[Entity]) -> list[Entity]:
    """Убрать частые однословные нарицательные, ошибочно принятые за PERSON.

    Группы строятся по нормализованному ключу, чтобы «Абонент» и «Абонента»
    считались одной повторяющейся ролью. Считаются разные координаты, а не
    число источников на одном месте: перекрывающиеся сигналы не должны
    искусственно поднимать частоту. Любой морфологический разбор ``Surn``,
    ``Name`` или ``Patr`` сохраняет всю группу — для recall имён это более
    безопасное решение, чем один лишь числовой порог.
    """
    grouped: dict[str, list[Entity]] = defaultdict(list)
    for entity in entities:
        if entity.type != EntityType.PERSON or not _single_common_noun(entity):
            continue
        normalized = entity.normalized or normalize_value(EntityType.PERSON, entity.text)
        if normalized:
            grouped[normalized].append(entity)

    rejected_locations = {
        (entity.segment_order, entity.start, entity.end)
        for candidates in grouped.values()
        if len({(item.segment_order, item.start, item.end) for item in candidates})
        >= _COMMON_NOUN_PERSON_MIN_OCCURRENCES
        for entity in candidates
    }
    return [
        entity
        for entity in entities
        if entity.type != EntityType.PERSON
        or (entity.segment_order, entity.start, entity.end) not in rejected_locations
    ]
