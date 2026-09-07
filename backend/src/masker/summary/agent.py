"""Сборка ContractSummary из результатов детекции и профилирования."""

from __future__ import annotations

from datetime import UTC, datetime

from masker.model import Entity, EntityType, Profile
from masker.summary.model import ContractParty, ContractSummary

#: Нормализованные названия роли «заказчик» — сравниваем casefold.
_CUSTOMER_ROLES = frozenset({"заказчик", "покупатель", "получатель"})
#: Нормализованные названия роли «поставщик/исполнитель».
_SUPPLIER_ROLES = frozenset({"поставщик", "исполнитель", "продавец", "подрядчик"})


def _party_from_profile(profile: Profile, entities: list[Entity]) -> ContractParty:
    """Извлечь ContractParty из профиля: имя (org_name или person), ИНН, ОГРН."""
    entity_map = {member.ref: member.entity for member in profile.members}

    name: str | None = None
    inn: str | None = None
    ogrn: str | None = None

    for member in profile.members:
        entity = entity_map[member.ref]
        if (entity.type == EntityType.ORG_NAME and name is None) or (
            entity.type == EntityType.PERSON and name is None
        ):
            name = entity.text
        elif entity.type == EntityType.INN:
            inn = entity.text
        elif entity.type == EntityType.OGRN:
            ogrn = entity.text

    return ContractParty(
        name=name,
        role_title=profile.role_title or None,
        inn=inn,
        ogrn=ogrn,
    )


def _find_party(
    profiles: list[Profile],
    entities: list[Entity],
    role_set: frozenset[str],
) -> ContractParty | None:
    for profile in profiles:
        if profile.role_title.casefold() in role_set:
            return _party_from_profile(profile, entities)
    return None


def _unique_ordered(texts: list[str]) -> list[str]:
    """Уникальные тексты, сохраняя порядок первого появления."""
    seen: set[str] = set()
    result: list[str] = []
    for t in texts:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def build_summary(
    entities: list[Entity],
    profiles: list[Profile],
    llm_calls: int = 0,
    generated_at: str | None = None,
) -> ContractSummary:
    """Собрать карточку договора из результатов детекции и профилирования.

    Вызывается детерминированно: LLM не трогает. ``payment_terms`` заполняется
    из детектора ``PaymentTermsDetector`` (Фаза 2) — regex без LLM.
    ``generated_at=None`` → текущий UTC-момент; передать пустую строку,
    чтобы получить детерминированный вывод (граф, тесты).
    """
    customer = _find_party(profiles, entities, _CUSTOMER_ROLES)
    supplier = _find_party(profiles, entities, _SUPPLIER_ROLES)

    federal_laws = _unique_ordered([e.text for e in entities if e.type == EntityType.FEDERAL_LAW])
    contract_amount = next((e.text for e in entities if e.type == EntityType.CONTRACT_AMOUNT), None)
    delivery_periods = _unique_ordered(
        [e.text for e in entities if e.type == EntityType.DELIVERY_PERIOD]
    )
    payment_terms_list = _unique_ordered(
        [e.text for e in entities if e.type == EntityType.PAYMENT_TERMS]
    )
    payment_terms = "; ".join(payment_terms_list) if payment_terms_list else None
    contract_number = next((e.text for e in entities if e.type == EntityType.CONTRACT_NUMBER), None)

    return ContractSummary(
        customer=customer,
        supplier=supplier,
        federal_law=federal_laws,
        contract_amount=contract_amount,
        delivery_periods=delivery_periods,
        payment_terms=payment_terms,
        contract_number=contract_number,
        generated_at=datetime.now(UTC).isoformat() if generated_at is None else generated_at,
        llm_calls=llm_calls,
    )
