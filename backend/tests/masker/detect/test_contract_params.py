"""Тесты детекторов коммерческих параметров.

Покрывает: federal_law, contract_amount, delivery_period, payment_terms.
"""

from __future__ import annotations

import pytest

from masker.detect.contract_params import (
    ContractAmountDetector,
    DeliveryPeriodDetector,
    PaymentTermsDetector,
)
from masker.detect.rules import RuleDetector
from masker.model import Anchor, Document, EntityType, Segment, Source


def _doc(*texts: str) -> Document:
    return Document(
        path="test.docx",
        fmt="docx",
        segments=[
            Segment(text=t, anchor=Anchor(fmt="docx", locator=("body", i)), order=i)
            for i, t in enumerate(texts)
        ],
    )


def _detect_rules(text: str) -> list[tuple[str, str]]:
    entities = RuleDetector().detect(_doc(text))
    return [(e.type, e.text) for e in entities]


def _detect_amount(text: str) -> list[str]:
    entities = ContractAmountDetector().detect(_doc(text))
    return [e.text for e in entities]


def _detect_delivery(*texts: str) -> list[str]:
    entities = DeliveryPeriodDetector().detect(_doc(*texts))
    return [e.text for e in entities]


def _detect_payment(*texts: str) -> list[str]:
    entities = PaymentTermsDetector().detect(_doc(*texts))
    return [e.text for e in entities]


# ---------------------------------------------------------------------------
# federal_law (rules.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Закупка проводится по 44-ФЗ.", "44-ФЗ"),
        ("в соответствии с 223 ФЗ", "223 ФЗ"),
        ("требования 615ФЗ", "615ФЗ"),
        ("согласно 275-ФЗ о гособоронзаказе", "275-ФЗ"),
    ],
)
def test_federal_law_detected(text: str, expected: str) -> None:
    hits = _detect_rules(text)
    assert (EntityType.FEDERAL_LAW, expected) in hits


def test_federal_law_not_triggered_by_arbitrary_number() -> None:
    """Произвольное «99-ФЗ» не попадает в список — фиксированный набор."""
    hits = _detect_rules("согласно 99-ФЗ о чём-то")
    assert not any(t == EntityType.FEDERAL_LAW for t, _ in hits)


def test_federal_law_not_triggered_by_contract_number_44_2026() -> None:
    """Номер договора «44/2026» не должен давать federal_law."""
    hits = _detect_rules("ДОГОВОР ПОСТАВКИ № 44/2026")
    assert not any(t == EntityType.FEDERAL_LAW for t, _ in hits)


# ---------------------------------------------------------------------------
# contract_amount
# ---------------------------------------------------------------------------


def test_contract_amount_detected_with_context() -> None:
    text = "Цена договора составляет 1 500 000 рублей, включая НДС."
    result = _detect_amount(text)
    assert result, "Должна быть найдена сумма договора"
    assert any("1 500 000 рублей" in v or "1 500 000" in v for v in result)


def test_contract_amount_requires_context() -> None:
    """Сумма без признаков договорной цены не попадает в contract_amount."""
    text = "Оплата 500 рублей за товар."
    assert _detect_amount(text) == []


def test_contract_amount_detected_across_segments() -> None:
    """Признак цены договора в одном сегменте, сумма в следующем — находим."""
    entities = ContractAmountDetector().detect(
        _doc(
            "Общая стоимость по договору:",
            "250 000 руб. без НДС.",
        )
    )
    assert entities, "Сумма должна быть найдена при контексте в соседнем сегменте"
    assert entities[0].type == EntityType.CONTRACT_AMOUNT


def test_contract_amount_source_and_confidence() -> None:
    text = "Стоимость договора — 100 000 рублей."
    entities = ContractAmountDetector().detect(_doc(text))
    assert entities
    assert entities[0].source == Source.RULE
    assert entities[0].confidence >= 0.8


# ---------------------------------------------------------------------------
# delivery_period
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Поставка осуществляется в течение 30 рабочих дней с момента оплаты.",
        "Товар отгружается в течение 5 дней.",
        "Поставщик обязан поставить не позднее 10 рабочих дней с момента подписания.",
        "Срок поставки — 14 календарных дней.",
        "Срок поставки: 7 дней.",
        "30 рабочих дней с момента получения заявки.",
    ],
)
def test_delivery_period_detected(text: str) -> None:
    result = _detect_delivery(text)
    assert result, f"Срок поставки не найден в: {text!r}"


def test_delivery_period_type_and_source() -> None:
    entities = DeliveryPeriodDetector().detect(_doc("в течение 10 рабочих дней"))
    assert entities
    assert entities[0].type == EntityType.DELIVERY_PERIOD
    assert entities[0].source == Source.RULE


def test_delivery_period_no_false_positives_on_plain_number() -> None:
    """Просто число без «дней» не должно давать срок поставки."""
    assert _detect_delivery("Сумма 30 рублей.") == []
    assert _detect_delivery("Количество: 10 единиц товара.") == []


def test_delivery_period_no_duplicates_same_span() -> None:
    """Если два паттерна срабатывают на одном спане, сущность одна."""
    text = "Срок поставки — 30 рабочих дней."
    starts = [e.start for e in DeliveryPeriodDetector().detect(_doc(text))]
    assert len(starts) == len(set(starts)), "Дублирующихся сущностей по одному спану быть не должно"


# ---------------------------------------------------------------------------
# payment_terms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "texts",
    [
        (
            "Порядок расчётов.",
            "Оплата производится в течение 30 рабочих дней с момента подписания акта приёмки.",
        ),
        (
            "Условия оплаты.",
            "Аванс 30% вносится в течение 5 банковских дней с даты подписания договора.",
        ),
        ("Порядок расчётов.", "100% постоплата в течение 90 дней."),
        ("Расчёты по договору.", "не позднее 15 банковских дней со дня получения счёта."),
    ],
)
def test_payment_terms_detected_with_context(texts: tuple[str, ...]) -> None:
    result = _detect_payment(*texts)
    assert result, f"Условия оплаты не найдены в: {texts!r}"


def test_payment_terms_requires_payment_context() -> None:
    """Срок поставки без ключевых слов раздела оплаты не детектируется."""
    assert _detect_payment("Сроки поставки.", "Товар поставляется в течение 10 рабочих дней.") == []


def test_payment_terms_not_triggered_without_context() -> None:
    """Произвольные числа без контекста раздела оплаты не попадают в payment_terms."""
    assert _detect_payment("Количество: 30 единиц товара.") == []


def test_payment_terms_type_and_source() -> None:
    entities = PaymentTermsDetector().detect(_doc("Порядок расчётов.", "100% постоплата."))
    assert entities
    assert entities[0].type == EntityType.PAYMENT_TERMS
    assert entities[0].source == Source.RULE
