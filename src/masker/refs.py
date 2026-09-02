"""Стабильные ссылки на сущности между агентами."""

from __future__ import annotations

from masker.model import Entity


def entity_sort_key(entity: Entity) -> tuple[int, int, int, str]:
    """Порядок сущностей в тексте, независимый от порядка входного списка."""
    return (entity.segment_order, entity.start, entity.end, entity.type)


class EntityIndex:
    """Двустороннее соответствие сущностей и ссылок ``E1..En``."""

    def __init__(self, entities: list[Entity]) -> None:
        ordered = sorted(entities, key=entity_sort_key)
        self._by_id = {id(entity): f"E{number}" for number, entity in enumerate(ordered, 1)}
        self._by_ref = {
            ref: entity for entity, ref in ((item, self._by_id[id(item)]) for item in ordered)
        }

    def ref(self, entity: Entity) -> str:
        """Вернуть стабильную ссылку на переданную сущность."""
        try:
            return self._by_id[id(entity)]
        except KeyError as error:
            raise KeyError("Сущность отсутствует в индексе") from error

    def entity(self, ref: str) -> Entity:
        """Вернуть сущность по ссылке."""
        return self._by_ref[ref]

    def refs(self) -> list[str]:
        """Вернуть все ссылки в текстовом порядке."""
        return list(self._by_ref)
