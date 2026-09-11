import dataclasses
import logging
from dataclasses import dataclass

import pytest

from masker.detect.agent import DetectAgent
from masker.entity_types import EntityTypeRegistry, EntityTypeSpec
from masker.model import Anchor, ConfidenceLevel, Document, Entity, EntityType, Segment, Source


@dataclass
class StubDetector:
    name: str
    source: Source
    priority: int
    entities: list[Entity]

    def detect(self, document: Document) -> list[Entity]:
        return self.entities


def _document(text: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[Segment(text, Anchor("docx", ("body", 0)), 0)],
    )


def test_rule_carves_hole_in_org_span() -> None:
    text = 'ООО "Ромашка" (ИНН 3662103003), в лице директора'
    document = _document(text)
    number = text.index("3662103003")
    model = StubDetector(
        "model",
        Source.NER,
        50,
        [Entity(EntityType.ORG_NAME, text[: number + 10], 0, 0, number + 10, Source.NER)],
    )
    rule = StubDetector(
        "rule",
        Source.RULE,
        100,
        [Entity(EntityType.INN, "3662103003", 0, number, number + 10, Source.RULE)],
    )

    result = DetectAgent([model, rule]).detect(document)

    assert [(item.type, item.text) for item in result.entities] == [
        (EntityType.ORG_NAME, 'ООО "Ромашка"'),
        (EntityType.INN, "3662103003"),
    ]


def test_carved_fragment_without_letters_dropped() -> None:
    text = "( 3662103003 )"
    document = _document(text)
    number = text.index("3662103003")
    model = StubDetector(
        "model", Source.NER, 50, [Entity(EntityType.ORG_NAME, text, 0, 0, len(text), Source.NER)]
    )
    rule = StubDetector(
        "rule",
        Source.RULE,
        100,
        [Entity(EntityType.INN, "3662103003", 0, number, number + 10, Source.RULE)],
    )

    # Уровень уверенности (Р8) не проверяется здесь — сущность критичного
    # типа (ИНН) всегда `CONFIRMED`, вне зависимости от того, что творится с
    # обрезкой соседних спанов, поэтому ожидание достраивается явным полем,
    # а не выясняется заново тем же кодом.
    expected = [
        dataclasses.replace(entity, level=ConfidenceLevel.CONFIRMED) for entity in rule.entities
    ]
    assert DetectAgent([model, rule]).detect(document).entities == expected


def test_rule_entity_is_never_carved() -> None:
    document = _document("ИНН 3662103003")
    first = StubDetector(
        "first", Source.RULE, 100, [Entity(EntityType.INN, "3662103003", 0, 4, 14, Source.RULE)]
    )
    second = StubDetector(
        "second", Source.RULE, 90, [Entity(EntityType.PASSPORT, "2103003", 0, 7, 14, Source.RULE)]
    )

    # ИНН — критичный тип, поэтому уровень (Р8) всегда `CONFIRMED` независимо
    # от исхода разрешения перекрытий, проверяемого этим тестом.
    expected = [
        dataclasses.replace(entity, level=ConfidenceLevel.CONFIRMED) for entity in first.entities
    ]
    assert DetectAgent([first, second]).detect(document).entities == expected


def test_custom_role_replaces_overlapping_noncritical_builtin_type() -> None:
    """Роль пользователя сохраняется вместо общего типа, не только для даты."""
    document = _document("Сумма договора 150 000 рублей")
    value = "150 000 рублей"
    start = document.segments[0].text.index(value)
    money = StubDetector(
        "money",
        Source.RULE,
        100,
        [Entity(EntityType.MONEY, value, 0, start, start + len(value), Source.RULE)],
    )
    role = StubDetector(
        "custom-role",
        Source.USER,
        50,
        [Entity("contract_price_role", value, 0, start, start + len(value), Source.USER)],
    )
    registry = EntityTypeRegistry.builtin().extend(
        [EntityTypeSpec("contract_price_role", "Цена договора", "ЦЕНА", builtin=False)]
    )

    result = DetectAgent([money, role], registry).detect(document)

    assert [(entity.type, entity.text) for entity in result.entities] == [
        ("contract_price_role", value)
    ]


def test_custom_role_cannot_replace_critical_builtin_and_logs_displacement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Уточнение роли не вправе снять маску критичного встроенного реквизита."""
    document = _document("ИНН 3662103003")
    value = "3662103003"
    start = document.segments[0].text.index(value)
    inn = StubDetector(
        "rules",
        Source.RULE,
        100,
        [Entity(EntityType.INN, value, 0, start, start + len(value), Source.RULE)],
    )
    role = StubDetector(
        "custom-role",
        Source.USER,
        50,
        [Entity("supplier_identifier", value, 0, start, start + len(value), Source.USER)],
    )
    registry = EntityTypeRegistry.builtin().extend(
        [EntityTypeSpec("supplier_identifier", "Код поставщика", "КОД", builtin=False)]
    )

    with caplog.at_level(logging.WARNING, logger="masker.detect.agent"):
        result = DetectAgent([inn, role], registry).detect(document)

    assert [entity.type for entity in result.entities] == [EntityType.INN]
    assert "supplier_identifier" in caplog.text
    assert "все вытеснены" in caplog.text


def test_detector_order_does_not_change_result() -> None:
    text = "ООО Ромашка, ИНН 3662103003"
    document = _document(text)
    number = text.index("3662103003")
    model = StubDetector(
        "model", Source.NER, 50, [Entity(EntityType.ORG_NAME, text, 0, 0, len(text), Source.NER)]
    )
    rule = StubDetector(
        "rule",
        Source.RULE,
        100,
        [Entity(EntityType.INN, "3662103003", 0, number, number + 10, Source.RULE)],
    )

    assert (
        DetectAgent([model, rule]).detect(document).entities
        == DetectAgent([rule, model]).detect(document).entities
    )


def _carved_texts(text: str, rule_type: EntityType, rule_text: str) -> list[str]:
    document = _document(text)
    start = text.index(rule_text)
    model = StubDetector(
        "model", Source.NER, 50, [Entity(EntityType.ORG_NAME, text, 0, 0, len(text), Source.NER)]
    )
    rule = StubDetector(
        "rule",
        Source.RULE,
        100,
        [Entity(rule_type, rule_text, 0, start, start + len(rule_text), Source.RULE)],
    )
    return [entity.text for entity in DetectAgent([model, rule]).detect(document).entities]


def test_carve_drops_unlisted_requisite_label() -> None:
    assert _carved_texts(
        'ООО "Ромашка" р/с 40702810100000000002',
        EntityType.BANK_ACCOUNT,
        "40702810100000000002",
    ) == ['ООО "Ромашка"', "40702810100000000002"]


def test_carve_drops_person_requisite_label() -> None:
    text = "Кузнецов Пётр Алексеевич паспорт 20 04 123456"
    document = _document(text)
    passport = "20 04 123456"
    start = text.index(passport)
    model = StubDetector(
        "model", Source.NER, 50, [Entity(EntityType.PERSON, text, 0, 0, len(text), Source.NER)]
    )
    rule = StubDetector(
        "rule",
        Source.RULE,
        100,
        [Entity(EntityType.PASSPORT, passport, 0, start, start + len(passport), Source.RULE)],
    )

    assert [entity.text for entity in DetectAgent([model, rule]).detect(document).entities] == [
        "Кузнецов Пётр Алексеевич",
        passport,
    ]


def test_non_leading_fragment_without_evidence_dropped() -> None:
    texts = _carved_texts(
        'ООО "Ромашка" ИНН 3662103003 является поставщиком оборудования',
        EntityType.INN,
        "3662103003",
    )
    assert texts == ['ООО "Ромашка"', "3662103003"]


def test_non_leading_fragment_with_form_kept() -> None:
    texts = _carved_texts('ИНН 3662103003 ООО "Ромашка"', EntityType.INN, "3662103003")
    assert texts == ["3662103003", 'ООО "Ромашка"']


def test_carved_fragment_keeps_balanced_quotes() -> None:
    texts = _carved_texts('ООО "Спорт 24" ИНН 3662103003', EntityType.INN, "3662103003")
    assert texts == ['ООО "Спорт 24"', "3662103003"]
    assert all(text.count('"') % 2 == 0 for text in texts)
