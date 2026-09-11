"""Формальные границы длины реквизитов.

Длина для этих типов — часть определения реквизита, а не порог качества
детектора. Предикат используется и после разрешения перекрытий: обрезанный
остаток исходно корректного кандидата не становится новым реквизитом.
"""

from __future__ import annotations

from collections.abc import Collection

from masker.model import Entity, EntityType

#: Число значащих разрядов у реквизитов, состоящих только из цифр.
_DIGIT_LENGTHS: dict[EntityType, frozenset[int]] = {
    # Расчётный/корреспондентский счёт содержит 20 цифр, лицевой счёт — 11.
    # Последний попадает сюда только из контекстного правила в `rules.py`.
    EntityType.BANK_ACCOUNT: frozenset({11, 20}),
    EntityType.INN: frozenset({10, 12}),
    EntityType.OGRN: frozenset({13, 15}),
    EntityType.SNILS: frozenset({11}),
    EntityType.BIK: frozenset({9}),
}

#: КПП допускает буквы в пятом и шестом разрядах, поэтому считаем не только
#: цифры, а все знаки самого значения без межразрядных пробелов.
_KPP_LENGTH = 9


def has_complete_requisite_length(entity_type: str, value: str) -> bool:
    """Соответствует ли длина значения нормативной длине его типа.

    Для типов вне списка ограничений предикат возвращает ``True``: это
    фильтр реквизитов, а не общий фильтр сущностей произвольных типов.
    """
    try:
        etype = EntityType(entity_type)
    except ValueError:
        return True
    if etype is EntityType.KPP:
        return len(value.replace(" ", "")) == _KPP_LENGTH
    lengths = _DIGIT_LENGTHS.get(etype)
    return lengths is None or sum(char.isdigit() for char in value) in lengths


def drop_incomplete_requisites(entities: Collection[Entity]) -> list[Entity]:
    """Убрать обрывки реквизитов до передачи результатов дальше по графу."""
    return [
        entity
        for entity in entities
        if has_complete_requisite_length(entity.type, entity.text)
    ]
