"""Реестр типов сущностей: встроенные и пользовательские.

Единственное место, которое знает полный набор активных типов в одной сессии.
Реестр иммутабелен: ``extend`` возвращает новый объект, глобального изменяемого
состояния нет.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from masker.model import CRITICAL_TYPES, EntityType


@dataclass(frozen=True, slots=True)
class EntityTypeSpec:
    """Описание одного типа сущности — встроенного или пользовательского."""

    id: str  # "inn", "shipment_date" — то, что лежит в Entity.type
    title: str  # «ИНН», «Дата отгрузки» — для отчёта и UI
    marker_label: str  # «ИНН», «ДАТА-ОТГРУЗКИ» — вставляется в compose_marker
    critical: bool = False
    builtin: bool = True


def builtin_specs() -> list[EntityTypeSpec]:
    """Один спек на каждый член EntityType, критичность из CRITICAL_TYPES."""
    _LABELS: dict[EntityType, tuple[str, str]] = {
        EntityType.ORG_NAME: ("Организация", "ОРГАНИЗАЦИЯ"),
        EntityType.PERSON: ("ФИО", "ФИО"),
        EntityType.INN: ("ИНН", "ИНН"),
        EntityType.KPP: ("КПП", "КПП"),
        EntityType.OGRN: ("ОГРН", "ОГРН"),
        EntityType.SNILS: ("СНИЛС", "СНИЛС"),
        EntityType.BANK_ACCOUNT: ("Банковский счёт", "СЧЁТ"),
        EntityType.BIK: ("БИК", "БИК"),
        EntityType.BANK_NAME: ("Банк", "БАНК"),
        EntityType.ADDRESS: ("Адрес", "АДРЕС"),
        EntityType.PHONE: ("Телефон", "ТЕЛЕФОН"),
        EntityType.EMAIL: ("Email", "ПОЧТА"),
        EntityType.PASSPORT: ("Паспорт", "ПАСПОРТ"),
        EntityType.CONTRACT_NUMBER: ("Номер договора", "ДОГОВОР"),
        EntityType.MONEY: ("Сумма", "СУММА"),
        EntityType.DATE: ("Дата", "ДАТА"),
        EntityType.BIRTH_DATE: ("Дата рождения", "РОЖДЕНИЕ"),
        EntityType.SITE: ("Сайт", "САЙТ"),
        EntityType.FEDERAL_LAW: ("Федеральный закон", "ФЗ"),
        EntityType.CONTRACT_AMOUNT: ("Сумма договора", "СУММА-ДОГОВОРА"),
        EntityType.DELIVERY_PERIOD: ("Срок поставки", "СРОК-ПОСТАВКИ"),
    }
    return [
        EntityTypeSpec(
            id=t.value,
            title=title,
            marker_label=marker_label,
            critical=(t in CRITICAL_TYPES),
            builtin=True,
        )
        for t, (title, marker_label) in _LABELS.items()
    ]


class EntityTypeRegistry:
    """Иммутабельный реестр типов сущностей.

    ``EntityTypeRegistry.builtin()`` — стартовая точка для встроенных типов.
    ``registry.extend(custom_specs)`` — добавить пользовательские типы,
    возвращает *новый* объект (исходный не меняется).
    """

    def __init__(self, specs: Iterable[EntityTypeSpec]) -> None:
        self._specs: dict[str, EntityTypeSpec] = {s.id: s for s in specs}

    # ------------------------------------------------------------------
    # Протокол реестра
    # ------------------------------------------------------------------

    def __contains__(self, type_id: object) -> bool:
        return type_id in self._specs

    def spec(self, type_id: str) -> EntityTypeSpec:
        try:
            return self._specs[type_id]
        except KeyError:
            known = ", ".join(sorted(self._specs))
            raise KeyError(f"Неизвестный тип сущности {type_id!r}. Известные: {known}") from None

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def critical_ids(self) -> frozenset[str]:
        return frozenset(s.id for s in self._specs.values() if s.critical)

    def is_critical(self, type_id: str) -> bool:
        """Вернуть критичность известного типа; неизвестный id считается ошибкой."""
        return self.spec(type_id).critical

    def extend(self, custom: Iterable[EntityTypeSpec]) -> EntityTypeRegistry:
        """Вернуть новый реестр с добавленными пользовательскими спеками."""
        merged = {**self._specs, **{s.id: s for s in custom}}
        return EntityTypeRegistry(merged.values())

    # ------------------------------------------------------------------
    # Фабрика встроенных типов
    # ------------------------------------------------------------------

    @classmethod
    def builtin(cls) -> EntityTypeRegistry:
        return cls(builtin_specs())
