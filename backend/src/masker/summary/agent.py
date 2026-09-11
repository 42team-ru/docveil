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
_FEDERAL_LAW_REFERENCE_RE = re.compile(
    r"\bфедеральн(?:ый|ого|ому|ым|ом|ыми|ые|ых)\s+закон(?:ами|ов|ом|а|у|е|ы)?"
    r"(?:\s+от\s+(?:\d{1,2}\.\d{1,2}\.\d{2,4}|\d{1,2}\s+[а-яё]+\s+\d{2,4})"
    r"(?:\s*(?:г(?:ода)?\.?)?)?)?\s*(?:№|n)\s*\d{1,4}\s*[-–]?\s*фз\b",
    re.IGNORECASE,
)
_FEDERAL_LAW_NUMBER_RE = re.compile(r"\b(?P<number>\d{1,4})\s*[-–]?\s*фз\b", re.I)
_PREAMBLE_PARTY_RE = re.compile(
    r"\b(?P<name>(?:министерств\w*|государственн\w*|акционерн\w*|публичн\w*|"
    r"федеральн\w*|общество\s+с\s+ограниченной\s+ответственностью|ооо|пао|ип)\b[^,]{3,500}?)\s*,?\s*"
    r"именуем\w*\s+в\s+дальнейшем\s*[«\"]?(?P<role>[^»\"\s,]+)",
    re.IGNORECASE,
)
_DELIVERY_ACTION_RE = re.compile(r"\b(?:постав\w*|оказ\w*\s+услуг|выполн\w*\s+работ)\b", re.I)
_NON_DELIVERY_RE = re.compile(
    r"\b(?:при[её]мк\w*|рассмотр\w*|ответ\w*|претензи\w*|расторжен\w*|"
    r"документ\w*)\b",
    re.I,
)
_CONTRACT_HEADER_RE = re.compile(
    r"(?:государственн\w*\s+)?контракт\w*\s+№\s*$|"
    r"(?:государственн\w*\s+)?договор\w*\s+№\s*$",
    re.I,
)
# Решение 11.09.2026: преамбула госконтракта часто одно длинное предложение.
# Ограничиваем цитату вокруг найденного значения, чтобы оператор видел факт,
# а не вычитывал страницу; значение всегда остаётся внутри окна.
_MAX_SOURCE_QUOTE = 360
_SUMMARY_PAYMENT_PATTERNS = (
    re.compile(
        r"\bоплата(?:\s+\w+){0,8}\s+"
        r"(?:производится|осуществляется|должна\s+быть\s+произведена)\b[^.;:\n]{0,500}",
        re.I,
    ),
    re.compile(r"\bавансировани[ея]\s+не\s+предусмотрен[оа]\b", re.I),
    re.compile(
        r"\b(?:заказчик|абонент)\s+перечисляет\b[^.;:\n]{0,500}"
        r"(?:аванс|в\s+течение\s+\d+)[^.;:\n]{0,500}",
        re.I,
    ),
    re.compile(r"\bпостоплата\s*(?:в\s+течение\s*)?\d*[^.;:\n]{0,180}", re.I),
    re.compile(
        r"\bв\s+течение\s+\d+\s*(?:рабочих|банковских|календарных)?\s*"
        r"(?:дн[её]й|дня|суток)\s+на\s+основании\s+сч[её]та\b[^.;:\n]{0,180}",
        re.I,
    ),
)
_SPACED_PAYMENT_PREFIX = "\0payment:"
_MAX_PAYMENT_FACTS = 3
_PAYMENT_STAGE_MARKERS = ("аванс", "авансов", "предоплат", "единовременно", "постоплата")
_PAYMENT_DEADLINE_MARKERS = ("в течение", "не позднее")
_PAYMENT_FINANCING_MARKERS = (
    "за счет средств",
    "за счёт средств",
    "средств бюджета",
    "кодам бюджетной классификации",
    "кбк",
)
_BROKEN_PAYMENT_FRAGMENT_RE = re.compile(
    r"(?:не\s+позднее|в\s+течение)\s{2,}"
    r"(?:(?:банковских|рабочих|календарных)\s*)?(?:дн[её]й|дня|суток)"
    r"|(?:не\s+позднее|в\s+течение)\s+"
    r"(?:(?:банковских|рабочих|календарных)\s*)?(?:дн[её]й|дня|суток)\s+"
    r"с\s+(?:даты|момента)\s+\d+\s*\(",
    re.I,
)


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
    text = segments.get(entity.segment_order, entity.text)
    if text == entity.text:
        # Решение 11.09.2026: синтетический или уже вырезанный кандидат тоже
        # попадает в карточку. Лимит цитаты не может зависеть от происхождения
        # сущности, иначе оператор снова читает длинный абзац.
        return _quote_around_value(text, 0, len(text))
    # Замерено 11.09.2026: PDF-сегмент мог быть целым абзацем на восемь
    # строк. Карточка должна вести к одному предложению вокруг значения, а
    # не заставлять оператора снова читать страницу.
    before = text[: entity.start]
    starts = list(re.finditer(r"[.!?]\s+(?=[А-ЯЁA-Z])", before))
    start = starts[-1].end() if starts else 0
    after = text[entity.end :]
    if text[entity.end - 1 : entity.end] in ".!?" and re.match(r"\s+[А-ЯЁA-Z]", after):
        end = entity.end
    else:
        end_match = re.search(r"[.!?](?=\s|$)", after)
        end = entity.end + end_match.end() if end_match else len(text)
    raw_quote = text[start:end]
    leading = len(raw_quote) - len(raw_quote.lstrip())
    quote = raw_quote.strip()
    if len(quote) <= _MAX_SOURCE_QUOTE:
        return quote
    value_start = entity.start - start - leading
    value_end = entity.end - start - leading
    return _quote_around_value(quote, value_start, value_end)


def _quote_around_value(quote: str, value_start: int, value_end: int) -> str:
    """Обрезать длинную цитату по окну вокруг найденного значения."""
    # Решение 11.09.2026: начало огромной преамбулы не важнее ссылки на ФЗ.
    # Окно центрируется на факте и сохраняет достаточный контекст с обеих сторон.
    value_start = max(0, value_start)
    value_end = min(len(quote), max(value_start, value_end))
    ellipses = 2
    budget = max(0, _MAX_SOURCE_QUOTE - ellipses)
    if value_end - value_start >= budget:
        return quote[value_start : value_start + budget].rstrip() + "…"
    before = min(value_start, (budget - (value_end - value_start)) // 2)
    after = min(budget - (value_end - value_start) - before, len(quote) - value_end)
    before = min(value_start, budget - (value_end - value_start) - after)
    quote_start = value_start - before
    quote_end = value_end + after
    prefix = "…" if quote_start else ""
    suffix = "…" if quote_end < len(quote) else ""
    return prefix + quote[quote_start:quote_end].strip() + suffix


def _fact(entity: Entity, anchors: dict[int, Anchor], segments: dict[int, str]) -> ContractFact:
    return ContractFact(
        value=entity.text,
        source_quote=_source_quote(entity, segments),
        anchors=[_anchor(entity, anchors)],
        source=entity.source.value,
        status="found",
    )


#: Реквизиты, привязывающие человека к конкретному лицу. Профиль с одним лишь
#: именем и без единого такого реквизита стороной не считается — см.
#: ``_party_is_established``.
_PERSON_IDENTIFIERS: frozenset[EntityType] = frozenset(
    {
        EntityType.INN,
        EntityType.OGRN,
        EntityType.SNILS,
        EntityType.PASSPORT,
        EntityType.BIRTH_DATE,
        EntityType.ADDRESS,
        EntityType.BANK_ACCOUNT,
    }
)


def _party_name_entity(profile: Profile) -> Entity | None:
    """Название стороны: организация приоритетнее человека.

    Раньше брался первый попавшийся ``ORG_NAME`` или ``PERSON`` в порядке
    участников — и на `contract_04_bankruptcy.docx` стороной становился
    человек, хотя организация в том же профиле есть, просто идёт следом.
    Сторона договора — это организация, если она в профиле есть; человек
    остаётся стороной только там, где организации нет вовсе (физлицо, ИП).
    """
    members = [
        member.entity
        for member in profile.members
        if member.entity.type in {EntityType.ORG_NAME, EntityType.PERSON}
    ]
    organisation = next((entity for entity in members if entity.type == EntityType.ORG_NAME), None)
    return organisation or (members[0] if members else None)


def _party_is_established(profile: Profile) -> bool:
    """Достаточно ли доказательств, чтобы назвать этот профиль стороной.

    Организация — да. Человек — только если рядом есть хоть один реквизит,
    привязывающий его к лицу (ИНН, ОГРН, СНИЛС, паспорт, дата рождения,
    адрес, счёт).

    Замерено 10.09.2026 на `contract_pdf_02_school.pdf`: единственный профиль
    с ролью «Исполнитель» состоит из одного человека без единого реквизита —
    это директор из оборота «уполномоченным представителем … является …»,
    то есть ПОДПИСАНТ, а не сторона. Карточка называла исполнителем
    физлицо. Для сравнения, законные физлица-стороны выглядят иначе:
    `contract_06_address.docx` — человек плюс ИНН и адрес,
    `contract_07_dates.docx` — люди с датами рождения.

    Голое имя без реквизитов — упоминание, а не сторона.
    """
    types = {member.entity.type for member in profile.members}
    if EntityType.ORG_NAME in types:
        return True
    return bool(types & _PERSON_IDENTIFIERS)


def _party_from_profile(profile: Profile) -> ContractParty:
    name_entity = _party_name_entity(profile)
    name: str | None = name_entity.text if name_entity is not None else None
    inn: str | None = None
    ogrn: str | None = None
    for member in profile.members:
        entity = member.entity
        if entity.type == EntityType.INN:
            inn = entity.text
        elif entity.type == EntityType.OGRN:
            ogrn = entity.text
    return ContractParty(name=name, role_title=profile.role_title or None, inn=inn, ogrn=ogrn)


def _party_fact(profile: Profile) -> ContractFact:
    name_entity = _party_name_entity(profile)
    member = next(
        (member for member in profile.members if member.entity is name_entity),
        None,
    )
    if member is None:
        return ContractFact(status="not_found")
    return ContractFact(
        value=member.entity.text,
        source_quote=_quote_around_value(member.entity.text, 0, len(member.entity.text)),
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
    labelled = [profile for profile in profiles if profile.role_title.casefold() in roles]
    candidates = [profile for profile in labelled if _party_is_established(profile)]
    if not candidates:
        # Роль в документе названа, но доказательств стороны нет: сохраняем
        # найденное в alternatives, а не выдаём подписанта за сторону.
        # `not_found` здесь означает «сторона не установлена», ровно как
        # требует Д1 — «не обнаружено», а не доказанное отсутствие.
        weak = [fact for fact in (_party_fact(profile) for profile in labelled) if fact.value]
        return None, ContractFact(
            status="not_found",
            alternatives=[
                FactAlternative(
                    value=fact.value or "",
                    source=fact.source or Source.RULE.value,
                    anchors=fact.anchors,
                )
                for fact in weak
            ],
        )
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


def _profiles_for_summary(
    profiles: list[Profile], entities: list[Entity], document: Document | None
) -> list[Profile]:
    """Вернуть профили для карточки, не включая профильный LLM-проход для PDF.

    Граф отключает профильный узел на PDF, поэтому в ``summary_node`` приходит
    пустой список даже при явных «Заказчик»/«Исполнитель» в документе. Для
    карточки достаточно уже найденных сущностей и структурных меток: это
    локальный детерминированный проход, не меняющий ``State`` и план масок.
    """
    if profiles or document is None:
        return profiles
    from masker.detect.result import DetectionResult, build_pii_chunks
    from masker.profile import ProfileAgent

    return (
        ProfileAgent(None)
        .profile(document, DetectionResult(entities, build_pii_chunks(document.segments, entities)))
        .profiles
    )


def _preamble_parties(document: Document | None) -> dict[str, tuple[ContractParty, ContractFact]]:
    """Извлечь полные стороны из преамбулы, если профиль распался на куски."""
    if document is None:
        return {}
    parties: dict[str, tuple[ContractParty, ContractFact]] = {}
    role_map = {
        "заказчик": "customer",
        "покупатель": "customer",
        "исполнитель": "supplier",
        "поставщик": "supplier",
        "продавец": "supplier",
    }
    for segment in sorted(document.segments, key=lambda item: item.order):
        for match in _PREAMBLE_PARTY_RE.finditer(segment.text):
            role_title = match.group("role")
            role = role_map.get(role_title.casefold())
            if role is None or role in parties:
                continue
            name = match.group("name").strip(" ,")
            name_start = match.start("name")
            # Замерено 11.09.2026 на brsc-contract.pdf: NER оставлял у
            # заказчика «Государственный комитет», а исполнителя вовсе не
            # создавал. В преамбуле оба полных названия уже есть до
            # «именуемый в дальнейшем», поэтому ей доверяем прежде профиля.
            fact = ContractFact(
                value=name,
                source_quote=_quote_around_value(
                    match.group(0).strip(),
                    match.start("name") - match.start(),
                    match.end("name") - match.start(),
                ),
                anchors=[
                    FactAnchor(
                        fmt=segment.anchor.fmt,
                        locator=list(segment.anchor.locator),
                        label=segment.anchor.label,
                        segment_order=segment.order,
                        start=name_start,
                        end=name_start + len(name),
                    )
                ],
                source=Source.RULE.value,
                status="found",
            )
            parties[role] = (ContractParty(name=name, role_title=role_title), fact)
    return parties


def _unique_entities(entities: list[Entity]) -> list[Entity]:
    seen: set[tuple[int, int, int, str]] = set()
    result: list[Entity] = []
    for entity in entities:
        key = (entity.segment_order, entity.start, entity.end, entity.text)
        if key not in seen:
            seen.add(key)
            result.append(entity)
    return result


def _federal_law_candidates(entities: list[Entity], document: Document | None) -> list[Entity]:
    """Вернуть уникальные ссылки на ФЗ только с номером закона.

    Базовые правила уже извлекают короткие номера закупочных законов. Если
    они ничего не нашли, карточка дополнительно распознаёт прямую ссылку
    «Федеральным законом от …» / «Федеральный закон о закупках». Это факт о
    договоре, а не PII, поэтому кандидат нужен карточке и не меняет набор
    сущностей для маскирования.
    """
    candidates = [entity for entity in entities if entity.type == EntityType.FEDERAL_LAW]
    if document is not None:
        for segment in sorted(document.segments, key=lambda item: item.order):
            for match in _FEDERAL_LAW_REFERENCE_RE.finditer(segment.text):
                candidates.append(
                    Entity(
                        type=EntityType.FEDERAL_LAW,
                        text=match.group().strip(),
                        segment_order=segment.order,
                        start=match.start(),
                        end=match.end(),
                        source=Source.RULE,
                        confidence=0.9,
                    )
                )
    unique: list[Entity] = []
    seen_numbers: set[str] = set()
    for entity in _unique_entities(candidates):
        law_number = _FEDERAL_LAW_NUMBER_RE.search(entity.text)
        if law_number is None:
            continue
        number = law_number.group("number")
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        unique.append(entity)
    # Замерено 11.09.2026 на brsc-contract.pdf: детектор выдавал несколько
    # «Федеральный закон» без номера и повторял 152-ФЗ. Без номера факт нельзя
    # ни проверить, ни дедуплицировать, поэтому он не попадает в карточку.
    return unique


def _amount_purpose(entity: Entity, quote: str) -> tuple[str, int]:
    start = max(0, entity.start - 80)
    preceding = quote[start : entity.start].casefold()
    conditional_context = quote[max(0, entity.start - 80) : entity.end + 180].casefold()
    if re.search(r"если\s+цен[аы]\s+контракт\w*\s+превыша\w*", conditional_context):
        return "penalty_condition", -1_000
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
        (entity, *_amount_purpose(entity, _source_quote(entity, segments))) for entity in candidates
    ]
    # Замерено 11.09.2026 на arkhschool-68-183.pdf: ставка штрафа ПП №1042
    # содержит «если цена Контракта превышает ... и составляет ...» и раньше
    # выигрывала как цена. Условные пороги вообще не кандидаты на цену.
    rated = [item for item in rated if item[1] != "penalty_condition"]
    if not rated:
        return MoneyFact(status="not_found")
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
    value = _payment_value(entity)
    quote = value if value != entity.text else _source_quote(entity, segments)
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
        value=value,
        source_quote=quote,
        anchors=[_anchor(entity, anchors)],
        source=entity.source.value,
        status="found",
        stages=[stage],
    )


def _payment_value(entity: Entity) -> str:
    """Сделать пригодным для карточки условие из посимвольного PDF-текста."""
    if entity.text.startswith(_SPACED_PAYMENT_PREFIX):
        return entity.text.removeprefix(_SPACED_PAYMENT_PREFIX)
    compact = re.sub(r"\s+", "", entity.text).casefold()
    advance = re.search(r"авансовымплатежом.*?втечение(?P<days>\d+)банковскихдней.*?счет", compact)
    if advance is None:
        return entity.text
    # Решение 11.09.2026: PDF `dagestanschool` хранит кириллицу отдельными
    # глифами, поэтому дословная строка нечитабельна. Краткая нормализация
    # опирается только на найденные слова и якорь, а не на догадку модели.
    return (
        "авансовый платёж после подписания заказа: "
        f"в течение {advance.group('days')} банковских дней с момента получения счёта"
    )


def _summary_payment_candidates(entities: list[Entity], document: Document | None) -> list[Entity]:
    """Вернуть условия оплаты, восстановив пропущенные общим детектором."""
    payments = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.PAYMENT_TERMS]
    )
    if payments or document is None:
        return _ordered_payment_candidates(payments)
    recovered: list[Entity] = []
    # Решение 11.09.2026: карточка Д3 обязана показывать договорные условия,
    # даже когда общий детектор потерял их при разрешении перекрытий. Этот
    # узкий fallback не меняет результаты маскирования и работает только Д3.
    for segment in document.segments:
        for pattern in _SUMMARY_PAYMENT_PATTERNS:
            for match in pattern.finditer(segment.text):
                if any(
                    item.segment_order == segment.order
                    and item.start < match.end()
                    and match.start() < item.end
                    for item in recovered
                ):
                    continue
                recovered.append(
                    Entity(
                        type=EntityType.PAYMENT_TERMS,
                        text=match.group().strip(),
                        segment_order=segment.order,
                        start=match.start(),
                        end=match.end(),
                        source=Source.RULE,
                        confidence=1.0,
                    )
                )
    if recovered:
        return _ordered_payment_candidates(recovered)
    ordered_segments = sorted(document.segments, key=lambda item: item.order)
    for index, segment in enumerate(ordered_segments):
        nearby = ordered_segments[index : index + 3]
        compact = re.sub(r"\s+", "", "".join(item.text for item in nearby)).casefold()
        # Отдельное имя, а не повторное `match`: выше переменная уже связана
        # с результатом обязательного поиска и выведена как `Match[str]`,
        # поэтому присваивание сюда `Match[str] | None` ломает проверку типов.
        compact_match = re.search(
            r"авансовымплатежом.*?послеподписаниязаказа.*?"
            r"втечение(?P<days>\d+)банковскихдней.*?счет",
            compact,
        )
        if compact_match is None:
            continue
        # Решение 11.09.2026: тот же PDF отдаёт слова с пробелами между
        # буквами и переносит фразу по сегментам. Сначала находим условие без
        # пробелов, но оставляем якорь начала, чтобы оператор открыл источник.
        recovered.append(
            Entity(
                type=EntityType.PAYMENT_TERMS,
                text=(
                    _SPACED_PAYMENT_PREFIX + "авансовый платёж после подписания заказа: "
                    f"в течение {compact_match.group('days')} банковских дней "
                    "с момента получения счёта"
                ),
                segment_order=segment.order,
                start=0,
                end=len(segment.text),
                source=Source.RULE,
                confidence=1.0,
            )
        )
    return _ordered_payment_candidates(recovered)


def _ordered_payment_candidates(candidates: list[Entity]) -> list[Entity]:
    """Поставить полноценный срок оплаты раньше общей фразы о расчётах."""
    # Решение 11.09.2026: плоское поле `payment_terms` совместимо со старым
    # отчётом и берёт первый факт. Приоритет срока/этапа не даёт строке о
    # финансировании заслонить реальное условие оплаты.
    markers = ("аванс", "единовременно", "постоплата", "в течение", "не позднее")
    return sorted(
        candidates,
        key=lambda item: (
            -sum(marker in _payment_value(item).casefold() for marker in markers),
            item.segment_order,
            item.start,
        ),
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


def _delivery_candidates(
    entities: list[Entity], segments: dict[int, str], has_document: bool
) -> list[Entity]:
    """Оставить срок исполнения обязательства, а не внутренний срок сторон."""
    if not has_document:
        return entities
    selected = []
    for entity in entities:
        quote = _source_quote(entity, segments)
        if _NON_DELIVERY_RE.search(quote):
            continue
        selected.append(entity)
    # Замерено 11.09.2026 на arkhschool-68-183.pdf: приёмка материалов и
    # ответ на расторжение были названы сроком поставки. Если обязательство
    # поставить товар/оказать услугу не видно, честный результат — not_found.
    return selected


def _contract_number_fact(
    numbers: list[Entity], anchors: dict[int, Anchor], segments: dict[int, str]
) -> ContractFact:
    """Выбрать номер только из заголовка контракта, исключив протокол закупки."""
    if numbers and not segments:
        return _fact(numbers[0], anchors, segments)
    for entity in numbers:
        quote = segments.get(entity.segment_order, entity.text)
        prefix = quote[max(0, entity.start - 100) : entity.start].casefold()
        if "протокол" in prefix:
            continue
        if _CONTRACT_HEADER_RE.search(prefix):
            return _fact(entity, anchors, segments)
    # Замерено 11.09.2026 на brsc-contract.pdf: единственный кандидат был
    # номером протокола электронного аукциона. Номер поля не заполняем, пока
    # не увидим заголовок «контракт/договор №».
    return ContractFact(status="not_found")


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
    summary_profiles = _profiles_for_summary(profiles, entities, document)
    customer, customer_fact = _select_party(summary_profiles, _CUSTOMER_ROLES)
    supplier, supplier_fact = _select_party(summary_profiles, _SUPPLIER_ROLES)
    preamble_parties = _preamble_parties(document)
    customer, customer_fact = preamble_parties.get("customer", (customer, customer_fact))
    supplier, supplier_fact = preamble_parties.get("supplier", (supplier, supplier_fact))
    laws = _federal_law_candidates(entities, document)
    amounts = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.CONTRACT_AMOUNT]
    )
    deliveries = _delivery_candidates(
        _unique_entities(
            [entity for entity in entities if entity.type == EntityType.DELIVERY_PERIOD]
        ),
        segments,
        document is not None,
    )
    payments = _summary_payment_candidates(entities, document)
    numbers = _unique_entities(
        [entity for entity in entities if entity.type == EntityType.CONTRACT_NUMBER]
    )
    amount_fact = _money_fact(amounts, anchors, segments)
    number_fact = _contract_number_fact(numbers, anchors, segments)
    return ContractSummary(
        customer=customer,
        supplier=supplier,
        federal_law=[entity.text for entity in laws],
        contract_amount=amount_fact.value,
        delivery_periods=[entity.text for entity in deliveries],
        payment_terms=_payment_value(payments[0]) if payments else None,
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
