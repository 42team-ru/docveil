"""Тесты build_summary: детерминированная сборка ContractSummary из entities + profiles."""

from __future__ import annotations

from unittest import mock

import pytest

from masker.model import (
    Anchor,
    Document,
    Entity,
    EntityType,
    MaskPlan,
    Profile,
    ProfileMember,
    Replacement,
    Segment,
    Source,
)
from masker.summary import (
    ContractSummary,
    SummaryLeakError,
    build_summary,
    export_summary,
)

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


def test_federal_law_full_references_are_candidates_when_short_code_is_absent() -> None:
    texts = [
        "В соответствии с Федеральным законом от 06.04.2011 № 63-ФЗ.",
        "Применяется Федеральный закон о закупках.",
        "Требования установлены Федеральным законом от 02 марта 2024 года.",
        "Соблюдаются требования, установленные федеральными законами.",
    ]
    document = Document(
        path="contract.pdf",
        fmt="pdf",
        segments=[
            Segment(text=text, anchor=Anchor("pdf", ("page", i)), order=i)
            for i, text in enumerate(texts)
        ],
    )

    summary = build_summary([], [], document=document, generated_at="")

    assert summary.federal_law == [
        "Федеральным законом от 06.04.2011 № 63-ФЗ",
        "Федеральный закон о закупках",
        "Федеральным законом от 02 марта 2024 года",
        "федеральными законами",
    ]
    assert [fact.source_quote for fact in summary.federal_law_facts] == texts


def test_equal_contract_amount_candidates_are_ambiguous_not_first_match() -> None:
    entities = [
        _entity(EntityType.CONTRACT_AMOUNT, "500 000 руб."),
        _entity(EntityType.CONTRACT_AMOUNT, "1 000 000 руб."),
    ]
    s = build_summary(entities, [])
    assert s.contract_amount is None
    assert s.contract_amount_fact.status == "ambiguous"


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


def test_summary_derives_pdf_parties_without_graph_profiles() -> None:
    """PDF отключает profile-node; карточка сохраняет явные роли офлайн."""
    texts = [
        "ООО «Заказчик», именуемое в дальнейшем «Заказчик»,",
        "ИП Исполнитель, именуемый в дальнейшем «Исполнитель»,",
    ]
    document = Document(
        path="contract.pdf",
        fmt="pdf",
        segments=[
            Segment(text=text, anchor=Anchor("pdf", ("page", i)), order=i)
            for i, text in enumerate(texts)
        ],
    )
    entities = [
        Entity(
            type=EntityType.ORG_NAME,
            text="ООО «Заказчик»",
            segment_order=0,
            start=0,
            end=len("ООО «Заказчик»"),
            source=Source.RULE,
        ),
        Entity(
            type=EntityType.ORG_NAME,
            text="ИП Исполнитель",
            segment_order=1,
            start=0,
            end=len("ИП Исполнитель"),
            source=Source.RULE,
        ),
    ]

    summary = build_summary(entities, [], document=document, generated_at="")

    assert summary.customer is not None
    assert summary.customer.role_title == "Заказчик"
    assert summary.supplier is not None
    assert summary.supplier.role_title == "Исполнитель"


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


def test_amount_selects_contract_price_and_keeps_vat_and_advance_as_alternatives() -> None:
    text = (
        "Цена договора составляет 500 000 руб., включая НДС 100 000 руб.; "
        "аванс составляет 150 000 руб."
    )
    document = Document(
        path="contract.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=_ANCHOR, order=0)],
    )
    values = ["500 000 руб.", "100 000 руб.", "150 000 руб."]
    entities = [
        Entity(
            type=EntityType.CONTRACT_AMOUNT,
            text=value,
            segment_order=0,
            start=text.index(value),
            end=text.index(value) + len(value),
            source=Source.RULE,
        )
        for value in values
    ]

    summary = build_summary(entities, [], document=document)

    assert summary.contract_amount_fact.value == "500 000 руб."
    assert summary.contract_amount_fact.currency == "RUB"
    assert summary.contract_amount_fact.status == "found"
    assert summary.contract_amount_fact.anchors[0].locator == ["body", 0]
    assert {(item.value, item.purpose) for item in summary.contract_amount_fact.alternatives} == {
        ("100 000 руб.", "vat"),
        ("150 000 руб.", "advance"),
    }


def test_payment_fact_keeps_stage_fields_and_not_found_is_not_procurement_regime() -> None:
    text = "Условия оплаты: 100% постоплата в течение 90 календарных дней после подписания акта."
    entity = Entity(
        type=EntityType.PAYMENT_TERMS,
        text="100% постоплата",
        segment_order=0,
        start=text.index("100%"),
        end=text.index("постоплата") + len("постоплата"),
        source=Source.RULE,
    )
    document = Document(
        path="contract.docx",
        fmt="docx",
        segments=[Segment(text=text, anchor=_ANCHOR, order=0)],
    )

    summary = build_summary([entity], [], document=document)

    stage = summary.payment_facts[0].stages[0]
    assert (stage.percentage, stage.days, stage.day_kind) == ("100%", 90, "календарных")
    assert stage.onset_event == "подписания акта"
    assert summary.procurement_regime.status == "not_found"
    assert summary.procurement_regime.value is None


def test_export_summary_masks_values_quotes_and_manual_mask_from_plan() -> None:
    original_name = "ООО «Ромашка»"
    original_inn = "7707000001"
    source = f"Заказчик {original_name}, ИНН {original_inn}."
    name = Entity(
        type=EntityType.ORG_NAME,
        text=original_name,
        segment_order=0,
        start=source.index(original_name),
        end=source.index(original_name) + len(original_name),
        source=Source.RULE,
    )
    inn = Entity(
        type=EntityType.INN,
        text=original_inn,
        segment_order=0,
        start=source.index(original_inn),
        end=source.index(original_inn) + len(original_inn),
        source=Source.USER,
    )
    profile = _profile("Заказчик", name, inn)
    summary = build_summary(
        [name, inn],
        [profile],
        document=Document(
            path="contract.docx",
            fmt="docx",
            segments=[Segment(text=source, anchor=_ANCHOR, order=0)],
        ),
    )
    plan = MaskPlan(
        replacements=(
            Replacement("E1", name, "[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]", "G1", "P1", _ANCHOR),
            Replacement("E2", inn, "[ЗАКАЗЧИК-ИНН]", "G2", "P1", _ANCHOR),
        ),
        groups=(),
        skipped=(),
        requested_types=(),
    )

    exported = export_summary(summary, plan)
    payload = str(exported).encode("utf-8")

    assert original_name.encode("utf-8") not in payload
    assert original_inn.encode("utf-8") not in payload
    assert exported["customer"]["name"] == "[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]"
    assert exported["customer"]["inn"] == "[ЗАКАЗЧИК-ИНН]"


# --- сторона договора: организация приоритетнее, голое имя стороной не считается ---


def test_party_name_prefers_organisation_over_person() -> None:
    """Организация в профиле есть — значит стороной является она, а не человек.

    Замерено на `contract_04_bankruptcy.docx`: организация в профиле стоит
    ПОСЛЕ человека, и прежний выбор «первый попавшийся ORG_NAME или PERSON»
    делал стороной физлицо.
    """
    profile = _profile(
        "Поставщик",
        _entity(EntityType.PERSON, "Иванов Иван Иванович"),
        _entity(EntityType.ORG_NAME, "ООО «Север»"),
        _entity(EntityType.INN, "7707083893"),
    )

    summary = build_summary([], [profile])

    assert summary.supplier is not None
    assert summary.supplier.name == "ООО «Север»"
    assert summary.supplier_fact.status == "found"


def test_lone_person_without_requisites_is_not_a_party() -> None:
    """Профиль из одного имени без единого реквизита — подписант, не сторона.

    Замерено на `contract_pdf_02_school.pdf`: единственный профиль с ролью
    «Исполнитель» состоял из директора, названного в обороте «уполномоченным
    представителем … является …». Карточка выдавала физлицо за исполнителя.
    Найденное имя остаётся в `alternatives`, чтобы оператор видел, что мы
    там нашли, но стороной не объявляется.
    """
    profile = _profile("Исполнитель", _entity(EntityType.PERSON, "Зубрицкая Татьяна Ивановна"))

    summary = build_summary([], [profile])

    assert summary.supplier is None
    assert summary.supplier_fact.status == "not_found"
    assert [item.value for item in summary.supplier_fact.alternatives] == [
        "Зубрицкая Татьяна Ивановна"
    ]


def test_person_with_requisite_stays_a_party() -> None:
    """Физлицо-сторона — законный случай: `contract_06_address.docx` (человек
    плюс ИНН), `contract_07_dates.docx` (люди с датами рождения). Реквизит
    рядом с именем и отличает сторону от подписанта."""
    profile = _profile(
        "Продавец",
        _entity(EntityType.PERSON, "Сидорова Анна Петровна"),
        _entity(EntityType.BIRTH_DATE, "01.02.1980"),
    )

    summary = build_summary([], [profile])

    assert summary.supplier is not None
    assert summary.supplier.name == "Сидорова Анна Петровна"
    assert summary.supplier_fact.status == "found"


def test_export_raises_when_original_value_survives_masking() -> None:
    """Уцелевшее исходное значение обязано уронить прогон, а не уехать в отчёт.

    Карточка — обходной путь мимо всей маскировки документа: `report.json` и
    HTML отдают дальше, и побайтовые проверки артефакта до них не достают.
    Молчаливая утечка здесь хуже падения: упавший прогон видно, утёкший ИНН —
    нет (AGENTS.md, «Утечки нет»).
    """
    entity = _entity(EntityType.INN, "7707083893")
    plan = MaskPlan(
        replacements=(Replacement("E1", entity, "[ИНН-1]", "G1", "P1", _ANCHOR),),
        groups=(),
        skipped=(),
        requested_types=(),
    )
    summary = build_summary([], [])

    # Маскировка идёт точной заменой строки; ломаем именно её, чтобы проверить
    # финальную защиту, а не саму замену.
    with (
        mock.patch("masker.summary.export._mask_value", side_effect=lambda value, _r: value),
        pytest.raises(SummaryLeakError),
    ):
        export_summary(summary.model_copy(update={"brief_summary": "ИНН 7707083893"}), plan)
