"""Тесты EntityTypeRegistry и EntityTypeSpec (шаг 1 плана T1.13)."""

from __future__ import annotations

import pytest

from masker.entity_types import EntityTypeRegistry, EntityTypeSpec, builtin_specs
from masker.model import CRITICAL_TYPES, EntityType


def test_builtin_registry_matches_enum() -> None:
    r = EntityTypeRegistry.builtin()
    assert set(r.ids()) == {t.value for t in EntityType}


def test_critical_ids_match_CRITICAL_TYPES() -> None:
    r = EntityTypeRegistry.builtin()
    expected = frozenset(t.value for t in CRITICAL_TYPES)
    assert r.critical_ids() == expected


def test_registry_extend_returns_new_object() -> None:
    r = EntityTypeRegistry.builtin()
    custom = EntityTypeSpec(
        id="shipment_date",
        title="Дата отгрузки",
        marker_label="ДАТА-ОТГРУЗКИ",
        critical=False,
        builtin=False,
    )
    r2 = r.extend([custom])
    assert r2 is not r
    assert "shipment_date" not in r
    assert "shipment_date" in r2


def test_extend_does_not_mutate_original() -> None:
    r = EntityTypeRegistry.builtin()
    before_ids = r.ids()
    custom = EntityTypeSpec("x_custom", "X", "X", builtin=False)
    r.extend([custom])
    assert r.ids() == before_ids


def test_spec_raises_keyerror_with_known_list() -> None:
    r = EntityTypeRegistry.builtin()
    with pytest.raises(KeyError, match="inn"):
        r.spec("nonexistent_type_xyz")


def test_contains_builtin_type() -> None:
    r = EntityTypeRegistry.builtin()
    assert "inn" in r
    assert EntityType.INN in r  # StrEnum == str


def test_ids_are_sorted() -> None:
    r = EntityTypeRegistry.builtin()
    ids = r.ids()
    assert list(ids) == sorted(ids)


def test_builtin_specs_cover_all_entity_types() -> None:
    specs = builtin_specs()
    spec_ids = {s.id for s in specs}
    assert spec_ids == {t.value for t in EntityType}


def test_custom_type_in_extended_registry() -> None:
    r = EntityTypeRegistry.builtin()
    custom = EntityTypeSpec("product_name", "Наименование товара", "ТОВАР", builtin=False)
    r2 = r.extend([custom])
    spec = r2.spec("product_name")
    assert spec.marker_label == "ТОВАР"
    assert not spec.critical
    assert not spec.builtin


def test_critical_custom_type() -> None:
    r = EntityTypeRegistry.builtin()
    custom = EntityTypeSpec("secret_code", "Секретный код", "КОД", critical=True, builtin=False)
    r2 = r.extend([custom])
    assert "secret_code" in r2.critical_ids()
