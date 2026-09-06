"""Тесты build_summary: детерминированная сборка ContractSummary из entities + profiles."""

from __future__ import annotations

from masker.model import Anchor, Entity, EntityType, Profile, ProfileMember, Source
from masker.summary import ContractSummary, build_summary

_ANCHOR = Anchor(fmt="docx", locator=("body", 0))


def _entity(entity_type: str, text: str, seg: int = 0) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=seg,
        start=0,
        end=len(text),
        source=Source.RULE,
        confidence=0.9,
    )


def _profile(role: str, *entities: Entity) -> Profile:
    return Profile(
        id=f"prof-{role}",
        role_title=role,
        members=[
            ProfileMember(entity=e, anchor=_ANCHOR, ref=f"ref-{i}") for i, e in enumerate(entities)
        ],
    )


def test_returns_contract_summary_instance() -> None:
    result = build_summary([], [])
    assert isinstance(result, ContractSummary)


def test_empty_input_gives_all_none_fields() -> None:
    s = build_summary([], [])
    assert s.customer is None
    assert s.supplier is None
    assert s.federal_law == []
    assert s.contract_amount is None
    assert s.delivery_periods == []
    assert s.contract_number is None
    assert s.payment_terms is None


def test_federal_law_collected_unique_ordered() -> None:
    entities = [
        _entity(EntityType.FEDERAL_LAW, "44-ФЗ"),
        _entity(EntityType.FEDERAL_LAW, "223-ФЗ"),
        _entity(EntityType.FEDERAL_LAW, "44-ФЗ"),
    ]
    s = build_summary(entities, [])
    assert s.federal_law == ["44-ФЗ", "223-ФЗ"]


def test_contract_amount_first_match() -> None:
    entities = [
        _entity(EntityType.CONTRACT_AMOUNT, "500 000 руб."),
        _entity(EntityType.CONTRACT_AMOUNT, "1 000 000 руб."),
    ]
    s = build_summary(entities, [])
    assert s.contract_amount == "500 000 руб."


def test_delivery_periods_unique_ordered() -> None:
    entities = [
        _entity(EntityType.DELIVERY_PERIOD, "в течение 30 дней"),
        _entity(EntityType.DELIVERY_PERIOD, "не позднее 5 рабочих дней"),
        _entity(EntityType.DELIVERY_PERIOD, "в течение 30 дней"),
    ]
    s = build_summary(entities, [])
    assert s.delivery_periods == ["в течение 30 дней", "не позднее 5 рабочих дней"]


def test_contract_number_first_match() -> None:
    entities = [_entity(EntityType.CONTRACT_NUMBER, "№ 42/2026")]
    s = build_summary(entities, [])
    assert s.contract_number == "№ 42/2026"


def test_customer_matched_by_role_title_заказчик() -> None:
    org = _entity(EntityType.ORG_NAME, "ООО Покупатель")
    inn = _entity(EntityType.INN, "7707000001")
    profile = _profile("Заказчик", org, inn)
    s = build_summary([org, inn], [profile])
    assert s.customer is not None
    assert s.customer.name == "ООО Покупатель"
    assert s.customer.inn == "7707000001"
    assert s.customer.role_title == "Заказчик"


def test_supplier_matched_by_role_title_поставщик() -> None:
    org = _entity(EntityType.ORG_NAME, "ИП Продавцов")
    ogrn = _entity(EntityType.OGRN, "304500116000190")
    profile = _profile("Поставщик", org, ogrn)
    s = build_summary([org, ogrn], [profile])
    assert s.supplier is not None
    assert s.supplier.name == "ИП Продавцов"
    assert s.supplier.ogrn == "304500116000190"


def test_customer_role_case_insensitive() -> None:
    org = _entity(EntityType.ORG_NAME, "ФГБОУ ВО Тест")
    profile = _profile("ЗАКАЗЧИК", org)
    s = build_summary([org], [profile])
    assert s.customer is not None


def test_supplier_aliases_покупатель_and_исполнитель() -> None:
    org1 = _entity(EntityType.ORG_NAME, "ООО А")
    profile_buyer = _profile("Покупатель", org1)
    s1 = build_summary([org1], [profile_buyer])
    assert s1.customer is not None

    org2 = _entity(EntityType.ORG_NAME, "ООО Б")
    profile_exec = _profile("Исполнитель", org2)
    s2 = build_summary([org2], [profile_exec])
    assert s2.supplier is not None


def test_llm_calls_passed_through() -> None:
    s = build_summary([], [], llm_calls=7)
    assert s.llm_calls == 7


def test_generated_at_is_iso8601_nonempty() -> None:
    s = build_summary([], [])
    assert s.generated_at
    assert "T" in s.generated_at


def test_model_dump_is_json_serialisable() -> None:
    import json

    entities = [
        _entity(EntityType.FEDERAL_LAW, "44-ФЗ"),
        _entity(EntityType.CONTRACT_AMOUNT, "100 000 руб."),
        _entity(EntityType.DELIVERY_PERIOD, "в течение 10 дней"),
    ]
    s = build_summary(entities, [])
    data = s.model_dump()
    dumped = json.loads(json.dumps(data))
    assert dumped["federal_law"] == ["44-ФЗ"]
    assert dumped["contract_amount"] == "100 000 руб."
