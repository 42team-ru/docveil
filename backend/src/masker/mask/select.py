"""Фильтр «что искать»: реестр типов + запрос пользователя → набор сущностей.

Применяется в `PlanAgent` (T1.6), первой строкой, **после** детекции и
профилирования. Детекция всегда ищет все известные реестру типы — фильтр
только отбирает, что из найденного пойдёт в маркировку. Причины см. в
`docs/plans/T1.13-entity-type-registry.md`, раздел «Где применяется фильтр
"что искать": в плане, не в детекции».
"""

from __future__ import annotations

from collections.abc import Sequence

from masker.entity_types import EntityTypeRegistry
from masker.model import Entity

#: Служебное значение запроса: «все типы, известные реестру на момент вызова»,
#: включая пользовательские. Регистронезависимо.
_ALL = "all"


def resolve_requested_types(
    raw: Sequence[str],
    registry: EntityTypeRegistry,
) -> frozenset[str]:
    """Развернуть список типов из CLI/API в набор id реестра.

    `all` (в любом регистре) разворачивается в полный набор `registry.ids()`,
    включая пользовательские типы. Имена нормализуются `casefold()` и
    обрезаются по краям, пустые элементы игнорируются. Пустой результат и
    неизвестный id — ошибки `ValueError` с русским сообщением; для
    неизвестного id в сообщении перечислены все известные реестру id.
    """
    normalized = [item.strip().casefold() for item in raw]
    normalized = [item for item in normalized if item]

    if any(item == _ALL for item in normalized):
        return frozenset(registry.ids())

    if not normalized:
        raise ValueError("Список запрошенных типов пуст: нечего маскировать.")

    unknown = sorted({item for item in normalized if item not in registry})
    if unknown:
        known = ", ".join(registry.ids())
        raise ValueError(f"Неизвестные типы сущностей: {', '.join(unknown)}. Известные: {known}")

    return frozenset(normalized)


def filter_by_types(
    entities: list[Entity],
    requested: frozenset[str],
    registry: EntityTypeRegistry,
) -> list[Entity]:
    """Оставить сущности запрошенных типов. Порядок входа сохраняется.

    Реестр в параметрах — часть контракта, симметричного
    `resolve_requested_types`: `requested` предполагается набором id из этого
    же реестра, а не произвольных строк. Сам отбор сравнивает `entity.type`
    с `requested` напрямую, без обращения к реестру.
    """
    return [entity for entity in entities if entity.type in requested]
