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


def test_federal_law_requires_number_and_deduplicates_by_number() -> None:
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
    ]
    assert summary.federal_law_facts[0].source_quote == texts[0]


def test_federal_law_without_number_is_discarded_and_duplicate_number_is_one_fact() -> None:
    text = (
        "Федеральный закон применяется. Федеральный закон от 27 июля 2006 года № 152-ФЗ "
        "устанавливает требования. Федерального закона № 152-ФЗ достаточно."
    )
    document = Document(
        path="contract.pdf",
        fmt="pdf",
        segments=[Segment(text=text, anchor=_ANCHOR, order=0)],
    )
    bare = _entity(EntityType.FEDERAL_LAW, "Федеральный закон")

    summary = build_summary([bare], [], document=document, generated_at="")

    assert len(summary.federal_law) == 1
    assert "152-ФЗ" in summary.federal_law[0]


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


def test_conditional_penalty_amount_is_not_contract_price() -> None:
    text = "Штраф составляет 100 000 рублей, если цена Контракта превышает 100 млн. рублей."
    penalty = Entity(
        type=EntityType.CONTRACT_AMOUNT,
        text="100 000 рублей",
        segment_order=0,
        start=text.index("100 000 рублей"),
        end=text.index("100 000 рублей") + len("100 000 рублей"),
        source=Source.RULE,
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([penalty], [], document=document, generated_at="")

    assert summary.contract_amount is None
    assert summary.contract_amount_fact.status == "not_found"


def test_acceptance_or_claim_deadline_is_not_delivery_period() -> None:
    text = "Заказчик обязан рассмотреть документы не позднее 15 рабочих дней с даты получения."
    deadline = Entity(
        type=EntityType.DELIVERY_PERIOD,
        text="не позднее 15 рабочих дней",
        segment_order=0,
        start=text.index("не позднее"),
        end=text.index("дней") + len("дней"),
        source=Source.RULE,
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([deadline], [], document=document, generated_at="")

    assert summary.delivery_periods == []
    assert summary.delivery_facts == []


def test_protocol_number_is_not_contract_number() -> None:
    text = "Закупка проведена по протоколу от 25 ноября 2016 года № 0101200009516004978."
    protocol = Entity(
        type=EntityType.CONTRACT_NUMBER,
        text="0101200009516004978",
        segment_order=0,
        start=text.index("0101200009516004978"),
        end=text.index("0101200009516004978") + len("0101200009516004978"),
        source=Source.RULE,
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([protocol], [], document=document, generated_at="")

    assert summary.contract_number is None
    assert summary.contract_number_fact.status == "not_found"


def test_supplier_is_read_from_full_preamble_before_named_as() -> None:
    text = (
        "Государственный комитет Республики Башкортостан по информатизации, именуемый в дальнейшем "
        "«Заказчик», с одной стороны, и Акционерное общество «Башкирский регистр социальных карт», "
        "именуемое в дальнейшем «Исполнитель», с другой стороны."
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([], [], document=document, generated_at="")

    assert summary.supplier is not None
    assert summary.supplier.name == "Акционерное общество «Башкирский регистр социальных карт»"
    assert summary.supplier_fact.source_quote.endswith("«Исполнитель")


def test_fact_quote_is_one_sentence_not_whole_pdf_segment() -> None:
    text = "Первое предложение. Цена контракта составляет 500 000 руб. Третье предложение."
    amount = Entity(
        type=EntityType.CONTRACT_AMOUNT,
        text="500 000 руб.",
        segment_order=0,
        start=text.index("500 000 руб."),
        end=text.index("500 000 руб.") + len("500 000 руб."),
        source=Source.RULE,
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([amount], [], document=document, generated_at="")

    assert summary.contract_amount_fact.source_quote == "Цена контракта составляет 500 000 руб."


def test_fact_quote_has_limit_and_keeps_value_in_long_sentence() -> None:
    """Длинная преамбула не заставляет оператора читать её до ссылки на ФЗ."""
    law = "Федерального закона от 5 апреля 2013 г. № 44-ФЗ"
    text = "Преамбула " + "очень длинная " * 80 + law + " " + "продолжение " * 80 + "."
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([], [], document=document, generated_at="")

    quote = summary.federal_law_facts[0].source_quote
    assert quote is not None
    assert law in quote
    assert len(quote) <= 360


def test_every_card_fact_quote_has_the_same_length_limit() -> None:
    """Лимит цитаты одинаков для правил, профиля и длинного условия оплаты."""
    filler = "длинный фрагмент " * 50
    customer = _entity(EntityType.ORG_NAME, filler + "заказчик")
    supplier = _entity(EntityType.ORG_NAME, filler + "исполнитель")
    payment = _entity(
        EntityType.PAYMENT_TERMS,
        "Оплата " + filler + "в течение 10 рабочих дней с даты приёмки",
    )
    entities = [
        customer,
        supplier,
        payment,
        _entity(EntityType.FEDERAL_LAW, "Федерального закона № 44-ФЗ " + filler),
        _entity(EntityType.CONTRACT_AMOUNT, "1 000 рублей " + filler),
        _entity(EntityType.DELIVERY_PERIOD, "поставка " + filler),
        _entity(EntityType.CONTRACT_NUMBER, "№ 42 " + filler),
    ]
    summary = build_summary(
        entities,
        [_profile("Заказчик", customer), _profile("Исполнитель", supplier)],
        generated_at="",
    )
    assert summary.federal_law_facts
    assert summary.payment_facts
    assert summary.delivery_facts
    facts = [
        summary.customer_fact,
        summary.supplier_fact,
        summary.contract_amount_fact,
        summary.contract_number_fact,
        *summary.federal_law_facts,
        *summary.payment_facts,
        *summary.delivery_facts,
    ]

    assert all(fact.source_quote is not None and len(fact.source_quote) <= 360 for fact in facts)


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


@pytest.mark.parametrize(
    "text",
    [
        "Оплата производится в течение 10 рабочих дней с момента подписания акта.",
        "Оплата производится единовременно после оказания услуг.",
        "Оплата производится по факту оказания услуг.",
        "Авансирование не предусмотрено.",
        "Постоплата 30 дней после подписания акта.",
        "В течение 5 рабочих дней на основании счёта производится расчёт.",
    ],
)
def test_summary_recovers_common_payment_terms_without_detector_candidate(text: str) -> None:
    """Карточка извлекает обязательные условия оплаты из типовых формулировок."""
    document = Document(
        path="contract.docx", fmt="docx", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([], [], document=document, generated_at="")

    assert summary.payment_terms == text.rstrip(".")
    assert summary.payment_facts[0].source_quote == text


def test_summary_recovers_payment_from_character_spaced_pdf_text() -> None:
    """PDF с раздельными глифами всё равно даёт оператору читаемое условие."""
    text = (
        "Е д и н о в р е м е н н а я п л а т а в н о с и т с я а в а н с о в ы м п л а т е ж о м "
        "п о с л е п о д п и с а н и я з а к а з а "
        "в т е ч е н и е 5 б а н к о в с к и х д н е й с м о м е н т а п о л у ч е н и я с ч е т а."
    )
    document = Document(
        path="contract.pdf", fmt="pdf", segments=[Segment(text=text, anchor=_ANCHOR, order=0)]
    )

    summary = build_summary([], [], document=document, generated_at="")

    assert summary.payment_terms == (
        "авансовый платёж после подписания заказа: "
        "в течение 5 банковских дней с момента получения счёта"
    )
    assert summary.payment_facts[0].source_quote == summary.payment_terms


def test_payment_card_discards_financing_and_keeps_payment_deadline() -> None:
    """Источник денег не выдаётся за самостоятельное условие оплаты."""
    funding = _entity(
        EntityType.PAYMENT_TERMS,
        "Оплата услуг осуществляется за счет средств федерального бюджета по КБК.",
    )
    deadline = _entity(
        EntityType.PAYMENT_TERMS,
        "Оплата производится в течение 10 рабочих дней с даты подписания документа о приемке.",
    )

    summary = build_summary([funding, deadline], [], generated_at="")

    assert summary.payment_terms == deadline.text
    assert [fact.value for fact in summary.payment_facts] == [deadline.text]


def test_payment_card_discards_broken_pdf_word_order() -> None:
    """Число после единицы измерения — признак сломанного текстового слоя PDF."""
    broken = _entity(
        EntityType.PAYMENT_TERMS,
        "Оплата производится ежемесячно, не позднее   рабочих дней с даты 10 (десяти) "
        "подписания документа о приемке.",
    )
    fallback = _entity(
        EntityType.PAYMENT_TERMS,
        "Оплата должна быть произведена в течение 10 рабочих дней с момента выставления счета.",
    )

    summary = build_summary([broken, fallback], [], generated_at="")

    assert summary.payment_terms == fallback.text
    assert [fact.value for fact in summary.payment_facts] == [fallback.text]


def test_payment_card_keeps_advance_and_final_settlement() -> None:
    """Аванс и окончательный платёж — разные полезные этапы расчёта."""
    advance = _entity(
        EntityType.PAYMENT_TERMS,
        "Аванс в размере 90 процентов перечисляется после подписания контракта.",
    )
    final = _entity(
        EntityType.PAYMENT_TERMS,
        "Окончательный расчёт производится в течение 10 рабочих дней с даты приёмки.",
    )

    summary = build_summary([advance, final], [], generated_at="")

    assert {fact.value for fact in summary.payment_facts} == {advance.text, final.text}


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
