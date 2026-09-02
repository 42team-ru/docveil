"""Тесты фильтра «что искать» (T1.13, шаг 6, docs/plans/T1.13-entity-type-registry.md)."""

from __future__ import annotations

import pytest

from masker.entity_types import EntityTypeRegistry, EntityTypeSpec
from masker.mask.select import filter_by_types, resolve_requested_types
from masker.model import CRITICAL_TYPES, Entity, EntityType, Source


def _entity(entity_type: str, text: str) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=0,
        start=0,
        end=len(text),
        source=Source.RULE,
    )


def _registry_with_custom() -> EntityTypeRegistry:
    return EntityTypeRegistry.builtin().extend(
        [
            EntityTypeSpec(
                id="shipment_date",
                title="Дата отгрузки",
                marker_label="ДАТА-ОТГРУЗКИ",
                critical=False,
                builtin=False,
            )
        ]
    )


def test_all_expands_to_registry() -> None:
    """`--types all` обязан включать и встроенные, и пользовательские типы.

    Если реализация развернёт `all` только в `EntityType`, забыв про
    пользовательские id из `registry.extend(...)`, этот тест упадёт: набор
    `resolve_requested_types(["all"], registry)` окажется меньше `registry.ids()`.
    """
    registry = _registry_with_custom()

    resolved = resolve_requested_types(["all"], registry)

    assert resolved == frozenset(registry.ids())
    assert "shipment_date" in resolved


@pytest.mark.parametrize("spelling", ["ALL", "All", "  all  "])
def test_all_case_and_whitespace_insensitive(spelling: str) -> None:
    registry = EntityTypeRegistry.builtin()

    resolved = resolve_requested_types([spelling], registry)

    assert resolved == frozenset(registry.ids())


def test_normalizes_case_and_strips_whitespace() -> None:
    registry = EntityTypeRegistry.builtin()

    resolved = resolve_requested_types([" INN ", "Person"], registry)

    assert resolved == frozenset({"inn", "person"})


def test_ignores_empty_elements() -> None:
    registry = EntityTypeRegistry.builtin()

    resolved = resolve_requested_types(["inn", "", "   "], registry)

    assert resolved == frozenset({"inn"})


def test_empty_result_is_error() -> None:
    registry = EntityTypeRegistry.builtin()

    with pytest.raises(ValueError, match="пуст"):
        resolve_requested_types(["", "   "], registry)


def test_unknown_type_lists_known() -> None:
    """Опечатка в `--types` не должна тихо проигнорироваться.

    Сообщение обязано содержать и сам неизвестный id (иначе пользователь не
    поймёт, что опечатался), и перечень известных id (иначе не поймёт, что
    вводить вместо этого).
    """
    registry = EntityTypeRegistry.builtin()

    with pytest.raises(ValueError) as exc_info:
        resolve_requested_types(["inn", "innn"], registry)

    message = str(exc_info.value)
    assert "innn" in message
    for known_id in registry.ids():
        assert known_id in message


def test_filter_preserves_input_order() -> None:
    """`filter_by_types` не имеет права сортировать — порядок входа важен для
    отчёта и для последующей группировки в `PlanAgent`."""
    registry = EntityTypeRegistry.builtin()
    entities = [
        _entity(EntityType.PERSON, "Иванов"),
        _entity(EntityType.INN, "3662103003"),
        _entity(EntityType.PERSON, "Петров"),
        _entity(EntityType.ORG_NAME, 'ООО "Ромашка"'),
        _entity(EntityType.INN, "7707083893"),
    ]
    requested = frozenset({"person", "inn"})

    result = filter_by_types(entities, requested, registry)

    assert [e.text for e in result] == ["Иванов", "3662103003", "Петров", "7707083893"]


def test_filter_drops_unrequested_critical_type() -> None:
    """Фильтр действительно выбрасывает критичный тип, если его не запросили.

    Это осознанное поведение, а не дефект: инвариант «recall=1.0 для
    CRITICAL_TYPES» относится к детекции и к проверке `ValidateAgent`
    (который ищет утечки повторным прогоном детекторов по результату — см.
    план, раздел «Где применяется фильтр "что искать"»), а не к содержимому
    плана маскировки. Пользователь, попросивший замаскировать только
    `person`, сознательно получает документ без маркировки ИНН — план не
    обязан навязывать критичные типы сверх запроса.
    """
    registry = EntityTypeRegistry.builtin()
    inn = _entity(EntityType.INN, "3662103003")
    assert EntityType.INN in CRITICAL_TYPES
    entities = [_entity(EntityType.PERSON, "Иванов"), inn]
    requested = frozenset({"person"})

    result = filter_by_types(entities, requested, registry)

    assert inn not in result
    assert all(e.type != "inn" for e in result)


def test_filter_empty_requested_drops_everything() -> None:
    registry = EntityTypeRegistry.builtin()
    entities = [_entity(EntityType.PERSON, "Иванов")]

    result = filter_by_types(entities, frozenset(), registry)

    assert result == []


def test_filter_keeps_custom_type_entities() -> None:
    registry = _registry_with_custom()
    entities = [
        _entity("shipment_date", "12.02.2026"),
        _entity(EntityType.PERSON, "Иванов"),
    ]

    result = filter_by_types(entities, frozenset({"shipment_date"}), registry)

    assert [e.text for e in result] == ["12.02.2026"]
