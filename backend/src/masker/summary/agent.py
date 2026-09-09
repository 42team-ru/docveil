"""Детерминированная сборка фактов карточки договора."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from masker.model import Anchor, Document, Entity, EntityType, Profile, Source
from masker.summary.model import (
    ContractFact,
    ContractParty,
    ContractSummary,
    DeliveryFact,
    FactAlternative,
    FactAnchor,
    MoneyFact,
    PaymentFact,
    PaymentStage,
)

_CUSTOMER_ROLES = frozenset({"заказчик", "покупатель", "получатель"})
_SUPPLIER_ROLES = frozenset({"поставщик", "исполнитель", "продавец", "подрядчик"})
_AMOUNT_KEYWORDS = (
    "цена договора",
    "цена контракта",
    "стоимость договора",
    "стоимость контракта",
    "сумма договора",
    "общая стоимость",
    "цена поставки",
    "цена работ",
    "цена услуг",
    "итоговая стоимость",
)
_MONEY_RE = re.compile(r"\d[\d\s\u00a0]*(?:[.,]\d{1,2})?\s*(?:рублей|рубл[её]й|руб\.?|₽)", re.I)
_PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_DAYS_RE = re.compile(
    r"(?P<days>\d+)\s*(?P<kind>банковских|рабочих|календарных)?\s*"
    r"(?:дн[её]й|дня|суток)",
    re.I,
)
_EVENT_RE = re.compile(
    r"(?:(?:с|со)\s+(?:момента|дня|даты)\s+|после\s+)"
    r"(?P<event>[^.,;:]{3,120})",
    re.I,
)
_VAT_RE = re.compile(r"(?:включая|в\s+том\s+числе)?\s*НДС[^.,;]{0,80}", re.I)
_VAT_MARKERS = ("ндс", "налог на добавленную стоимость")
_ADVANCE_MARKERS = ("аванс", "авансов", "предоплат")
_PENALTY_MARKERS = ("штраф", "пен", "неустойк")
_SECURITY_MARKERS = ("обеспечен", "гарантийн")


def _anchor(entity: Entity, anchors: dict[int, Anchor]) -> FactAnchor:
    anchor = anchors.get(entity.segment_order)
    if anchor is None:
        anchor = Anchor("unknown", ("segment", entity.segment_order))
    return FactAnchor(
        fmt=anchor.fmt,
        locator=list(anchor.locator),
        label=anchor.label,
        segment_order=entity.segment_order,
        start=entity.start,
        end=entity.end,
    )


def _source_quote(entity: Entity, segments: dict[int, str]) -> str:
    return segments.get(entity.segment_order, entity.text)


def _fact(entity: Entity, anchors: dict[int, Anchor], segments: dict[int, str]) -> ContractFact:
    return ContractFact(
        value=entity.text,
        source_quote=_source_quote(entity, segments),
        anchors=[_anchor(entity, anchors)],
        source=entity.source.value,
        status="found",
    )


def _party_from_profile(profile: Profile) -> ContractParty:
    name: str | None = None
    inn: str | None = None
    ogrn: str | None = None
    for member in profile.members:
        entity = member.entity
        if entity.type in {EntityType.ORG_NAME, EntityType.PERSON} and name is None:
            name = entity.text
        elif entity.type == EntityType.INN:
            inn = entity.text
        elif entity.type == EntityType.OGRN:
            ogrn = entity.text
    return ContractParty(name=name, role_title=profile.role_title or None, inn=inn, ogrn=ogrn)


def _party_fact(profile: Profile) -> ContractFact:
    member = next(
        (
            member
            for member in profile.members
            if member.entity.type in {EntityType.ORG_NAME, EntityType.PERSON}
        ),
        None,
    )
    if member is None:
        return ContractFact(status="not_found")
    return ContractFact(
        value=member.entity.text,
        source_quote=member.entity.text,
        anchors=[
            FactAnchor(
                fmt=member.anchor.fmt,
                locator=list(member.anchor.locator),
                label=member.anchor.label,
                segment_order=member.entity.segment_order,
                start=member.entity.start,
                end=member.entity.end,
            )
        ],
        source=profile.source.value,
        status="found",
    )


def _select_party(
    profiles: list[Profile], roles: frozenset[str]
) -> tuple[ContractParty | None, ContractFact]:
    candidates = [profile for profile in profiles if profile.role_title.casefold() in roles]
    if not candidates:
        return None, ContractFact(status="not_found")
    if len(candidates) == 1:
        return _party_from_profile(candidates[0]), _party_fact(candidates[0])
    alternatives = []
    for profile in candidates:
        fact = _party_fact(profile)
        if fact.value is not None:
            alternatives.append(
                FactAlternative(
                    value=fact.value,
                    source=fact.source or Source.RULE.value,
                    anchors=fact.anchors,
                )
            )
    return None, ContractFact(status="ambiguous", alternatives=alternatives)


def _unique_entities(entities: list[Entity]) -> list[Entity]:
    seen: set[tuple[int, int, int, str]] = set()
    result: list[Entity] = []
    for entity in entities:
        key = (entity.segment_order, entity.start, entity.end, entity.text)
        if key not in seen:
            seen.add(key)
            result.append(entity)
    return result


def _amount_purpose(entity: Entity, quote: str) -> tuple[str, int]:
    start = max(0, entity.start - 80)
    preceding = quote[start : entity.start].casefold()
    # «включая НДС» следует после основной цены, поэтому смотрим на маркеры
    # назначения слева от конкретного числа: иначе цена ошибочно станет НДС.
    purposes = (
        ("vat", -100, _VAT_MARKERS),
        ("advance", -90, _ADVANCE_MARKERS),
        ("security", -80, _SECURITY_MARKERS),
        ("penalty", -70, _PENALTY_MARKERS),
    )
    nearest = max(
        (
            (preceding.rfind(marker), purpose, score)
            for purpose, score, markers in purposes
            for marker in markers
            if marker in preceding
        ),
        default=(-1, "", 0),
    )
    if nearest[0] >= 0:
        return nearest[1], nearest[2]
    lowered = quote.casefold()
    distances = [
        abs((lowered.find(keyword) + len(keyword) // 2) - entity.start)
        for keyword in _AMOUNT_KEYWORDS
        if keyword in lowered
    ]
    if distances:
        return "contract_price", 100 - min(distances)
    return "unspecified", 0


def _currency(value: str) -> str | None:
    return "RUB" if re.search(r"руб|₽", value, re.I) else None


def _money_fact(
    candidates: list[Entity], anchors: dict[int, Anchor], segments: dict[int, str]
) -> MoneyFact:
    if not candidates:
        return MoneyFact(status="not_found")
    rated = [
        (entity, *_amount_purpose(entity, _source_quote(entity, segments)))
        for entity in candidates
    ]
    rated.sort(key=lambda item: (-item[2], item[0].segment_order, item[0].start))
    selected, purpose, score = rated[0]
    alternatives = [
        FactAlternative(
            value=entity.text,
            purpose=alternative_purpose,
            source=entity.source.value,
            anchors=[_anchor(entity, anchors)],
        )
        for entity, alternative_purpose, _ in rated[1:]
    ]
    if len(rated) > 1 and rated[1][2] == score:
        return MoneyFact(
            status="ambiguous",
            alternatives=[
                FactAlternative(
                    value=entity.text,
                    purpose=alternative_purpose,
                    source=entity.source.value,
                    anchors=[_anchor(entity, anchors)],
                )
                for entity, alternative_purpose, _ in rated
            ],
        )
    quote = _source_quote(selected, segments)
    vat_match = _VAT_RE.search(quote)
    return MoneyFact(
        value=selected.text,
        source_quote=quote,
        anchors=[_anchor(selected, anchors)],
        source=selected.source.value,
        status="found",
        alternatives=alternatives,
        currency=_currency(selected.text),
        vat=vat_match.group().strip() if vat_match else None,
        purpose=purpose,
    )


def _day_fields(text: str) -> tuple[int | None, str | None]:
    match = _DAYS_RE.search(text)
    if match is None:
        return None, None
    kind = match.group("kind")
    return int(match.group("days")), kind.casefold() if kind else "календарных"


def _event(text: str) -> str | None:
    match = _EVENT_RE.search(text)
    return match.group("event").strip() if match else None


def _payment_fact(
    entity: Entity, anchors: dict[int, Anchor], segments: dict[int, str]
) -> PaymentFact:
    quote = _source_quote(entity, segments)
    days, day_kind = _day_fields(quote)
    percentage_match = _PERCENT_RE.search(quote)
    amount_match = _MONEY_RE.search(quote)
    stage = PaymentStage(
        percentage=percentage_match.group() if percentage_match else None,
        amount=amount_match.group() if amount_match else None,
        onset_event=_event(quote),
        days=days,
        day_kind=day_kind,
    )
    return PaymentFact(
        value=entity.text,
        source_quote=quote,
        anchors=[_anchor(entity, anchors)],
        source=entity.source.value,
        status="found",
        stages=[stage],
    )


def _delivery_fact(
    entity: Entity, anchors: dict[int, Anchor], segments: dict[int, str]
) -> DeliveryFact:
    quote = _source_quote(entity, segments)
    days, day_kind = _day_fields(entity.text)
    object_match = re.search(
        r"(?:поставка|поставить|отгрузка)\s+(?P<object>товар[^.,;:]*)", quote, re.I
    )
    return DeliveryFact(
        value=entity.text,
        source_quote=quote,
        anchors=[_anchor(entity, anchors)],
        source=entity.source.value,
        status="found",
        object_or_batch=object_match.group("object").strip() if object_match else None,
        onset_event=_event(quote),
        days=days,
        day_kind=day_kind,
    )


def build_summary(
    entities: list[Entity],
    profiles: list[Profile],
    llm_calls: int = 0,
    generated_at: str | None = None,
    document: Document | None = None,
) -> ContractSummary:
    """Собрать карточку из кандидатов правил, не вызывая LLM.

    Ранжирование суммы намеренно сохраняет невыбранные НДС/аванс/штраф в
    ``alternatives``. Поэтому карточка не выдаёт соседнее число за цену
    договора и сохраняет объяснимый источник выбора.
    """
    anchors = {segment.order: segment.anchor for segment in document.segments} if document else {}
    segments = {segment.order: segment.text for segment in document.segments} if document else {}
    customer, customer_fact = _select_party(profiles, _CUSTOMER_ROLES)
    supplier, supplier_fact = _select_party(profiles, _SUPPLIER_ROLES)
    laws = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.FEDERAL_LAW]
    )
    amounts = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.CONTRACT_AMOUNT]
    )
    deliveries = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.DELIVERY_PERIOD]
    )
    payments = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.PAYMENT_TERMS]
    )
    numbers = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.CONTRACT_NUMBER]
    )
    amount_fact = _money_fact(amounts, anchors, segments)
    number_fact = (
        _fact(numbers[0], anchors, segments) if numbers else ContractFact(status="not_found")
    )
    return ContractSummary(
        customer=customer,
        supplier=supplier,
        federal_law=[entity.text for entity in laws],
        contract_amount=amount_fact.value,
        delivery_periods=[entity.text for entity in deliveries],
        payment_terms=payments[0].text if payments else None,
        contract_number=number_fact.value,
        customer_fact=customer_fact,
        supplier_fact=supplier_fact,
        federal_law_facts=[_fact(entity, anchors, segments) for entity in laws],
        # Упоминание 44-/223-ФЗ не является доказательством режима закупки.
        procurement_regime=ContractFact(status="not_found"),
        contract_amount_fact=amount_fact,
        payment_facts=[_payment_fact(entity, anchors, segments) for entity in payments],
        delivery_facts=[_delivery_fact(entity, anchors, segments) for entity in deliveries],
        contract_number_fact=number_fact,
        generated_at=datetime.now(UTC).isoformat() if generated_at is None else generated_at,
        llm_calls=llm_calls,
    )
