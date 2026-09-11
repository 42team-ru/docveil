"""Разрешение пересечений внутри слоя правил по явной таблице приоритетов.

`rules.py` раньше разрешал пересечения через один общий список `PRIORITY` —
порядок типов внутри словаря решал всё, вне зависимости от того, прошла ли
конкретная находка контрольную сумму. Отсюда воспроизводимая утечка: строка
`"р/с 40702810100000012345 в банке, БИК 044525225"` теряла `bank_account`,
потому что регулярка телефона выедала двенадцать цифр из середины двадцати­
значного счёта, а телефон в `PRIORITY` внезапно оказывался «длиннее» после
обрезки — на самом деле побеждать должен был счёт просто потому, что он
прошёл проверку, а телефон нет (план T2.2.1, Р2).

Явная таблица приоритетов, пять правил:

1. Сущность, прошедшая контрольную сумму (или её эквивалент для форматных
   типов, которым мы всё равно доверяем — см. `VALIDATED_TYPES`),
   неприкосновенна: её никто не подвинет и не обрежет.
2. При пересечении двух валидированных побеждает более длинная.
3. Невалидированная сущность, целиком лежащая внутри валидированной,
   отбрасывается целиком.
4. Невалидированная сущность, пересекающая валидированную лишь частично,
   обрезается до неперекрытого остатка (может распасться на несколько
   фрагментов, если валидированная находится у неё внутри).
5. Разрешение пересечений модельных (NER/LLM) спанов с уже принятыми —
   отдельная логика в `DetectAgent._resolve_overlaps`/`_carve`
   (`src/masker/detect/agent.py`); этот модуль её не касается и не
   дублирует.
"""

from __future__ import annotations

from collections.abc import Iterable

from masker.detect.normalize import normalize_value
from masker.detect.requisites import has_complete_requisite_length
from masker.model import Entity, EntityType

#: Минимальная длина остатка после обрезки (правило 4) — однознаковый мусор
#: (например, случайно уцелевшая цифра) в отчёт не идёт.
MIN_FRAGMENT_LEN = 2

#: Типы, которые считаются прошедшими надёжную проверку, если вообще попали
#: в кандидаты: `_accept()` в `rules.py` уже отфильтровал негодные —
#: настоящая контрольная сумма (inn, ogrn, snils) либо формат и контекст,
#: которому мы доверяем как контрольной сумме (kpp — только в паре с ИНН
#: или меткой «КПП», план T2.2.1, Д8). БИК сюда намеренно не входит: у него
#: нет контрольной суммы, только признак учреждения ЦБ РФ в первых разрядах,
#: этого недостаточно для «неприкосновенности» — только для приоритета выше
#: нестрогих регулярок вроде телефона (см. `FALLBACK_PRIORITY`).
VALIDATED_TYPES: frozenset[EntityType] = frozenset(
    {
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.KPP,
        EntityType.REGISTRY_KEY,
        EntityType.POWER_OF_ATTORNEY_NUMBER,
        EntityType.IP_ADDRESS,
    }
)

#: Счёт валиден, только если его удалось проверить в паре с БИК —
#: `rules._confidence` в этом случае ставит 1.0, а без БИК рядом (формат
#: совпал, а проверить нечем) — 0.75. Порог строго между ними.
VALIDATED_BANK_ACCOUNT_CONFIDENCE = 1.0

#: Порядок между собой для того, что осталось невалидированным (правило 5
#: этого модуля — не спутать с правилом 5 в докстринге модуля, которое про
#: agent.py): более надёжный формат впереди. 20-значный `bank_account` без
#: БИК рядом (формат совпал, проверить нечем) всё равно куда надёжнее
#: произвольной регулярки телефона. Контекстный 11-значный лицевой счёт сюда
#: не попадает: `rules.py` выпускает его сразу с уверенностью 1.0.
FALLBACK_PRIORITY: tuple[EntityType, ...] = (
    EntityType.BANK_ACCOUNT,
    EntityType.PASSPORT,
    EntityType.BIK,
    EntityType.EMAIL,
    EntityType.PHONE,
    EntityType.SITE,
    EntityType.CONTRACT_NUMBER,
    EntityType.FEDERAL_LAW,
)


def is_validated(entity: Entity) -> bool:
    """Прошла ли сущность проверку понадёжнее голой регулярки (правило 1)."""
    if entity.type in VALIDATED_TYPES:
        return True
    if entity.type == EntityType.BANK_ACCOUNT:
        return entity.confidence >= VALIDATED_BANK_ACCOUNT_CONFIDENCE
    return False


def _fallback_rank(entity: Entity) -> int:
    try:
        return FALLBACK_PRIORITY.index(entity.type)
    except ValueError:
        return len(FALLBACK_PRIORITY)


def _overlaps(a: Entity, b: Entity) -> bool:
    return a.segment_order == b.segment_order and a.start < b.end and b.start < a.end


def _carve_against(candidate: Entity, blockers: list[Entity]) -> list[Entity]:
    """Вычесть из `candidate` пересечения с `blockers` (правила 3 и 4).

    Полностью перекрытый кандидат превращается в пустой список фрагментов —
    это и есть правило 3 (отбрасывание целиком) как частный случай.
    """
    intervals = sorted((max(candidate.start, b.start), min(candidate.end, b.end)) for b in blockers)
    fragments: list[tuple[int, int]] = []
    cursor = candidate.start
    for start, end in intervals:
        if cursor < start:
            fragments.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < candidate.end:
        fragments.append((cursor, candidate.end))

    carved: list[Entity] = []
    for start, end in fragments:
        if end - start < MIN_FRAGMENT_LEN:
            continue
        local_start = start - candidate.start
        local_end = end - candidate.start
        text = candidate.text[local_start:local_end]
        # Р13: остаток правильного кандидата после вычитания ИНН/КПП не
        # наследует его тип. Например, «1 » от кандидата счёта внутри ИКЗ
        # не может быть банковским счётом по определению.
        if not has_complete_requisite_length(candidate.type, text):
            continue
        carved.append(
            Entity(
                type=candidate.type,
                text=text,
                segment_order=candidate.segment_order,
                start=start,
                end=end,
                source=candidate.source,
                confidence=candidate.confidence,
                normalized=normalize_value(candidate.type, text),
            )
        )
    return carved


def resolve_overlaps(found: Iterable[Entity]) -> list[Entity]:
    """Разрешить пересечения внутри слоя правил по таблице приоритетов.

    Порядок применения ровно соответствует пяти правилам из докстринга
    модуля (правило 5 — не здесь, оно в `agent.py`).
    """
    entities = list(found)
    validated = [e for e in entities if is_validated(e)]
    unvalidated = [e for e in entities if not is_validated(e)]

    # Правило 2: среди валидированных при пересечении побеждает более
    # длинная; при равенстве длины — более надёжный формат, затем позиция
    # (детерминизм).
    kept_validated: list[Entity] = []
    for cand in sorted(
        validated,
        key=lambda e: (-(e.end - e.start), _fallback_rank(e), e.start),
    ):
        if not any(_overlaps(cand, k) for k in kept_validated):
            kept_validated.append(cand)

    # Правила 3 и 4: невалидированные обрезаются/отбрасываются об
    # валидированные, которые в этом же сегменте их пересекают.
    carved_unvalidated: list[Entity] = []
    for cand in unvalidated:
        blockers = [v for v in kept_validated if _overlaps(cand, v)]
        if not blockers:
            carved_unvalidated.append(cand)
            continue
        carved_unvalidated.extend(_carve_against(cand, blockers))

    # Остаточные пересечения среди самих невалидированных (в том числе
    # между обрезанными фрагментами разных типов) разрешаются приоритетом
    # надёжности формата, затем длиной.
    kept_unvalidated: list[Entity] = []
    for cand in sorted(
        carved_unvalidated,
        key=lambda e: (_fallback_rank(e), -(e.end - e.start), e.start),
    ):
        if not any(_overlaps(cand, k) for k in kept_validated + kept_unvalidated):
            kept_unvalidated.append(cand)

    result = kept_validated + kept_unvalidated
    return sorted(result, key=lambda e: (e.segment_order, e.start, e.end, e.type))
