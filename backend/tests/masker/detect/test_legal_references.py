"""Тесты отделения публичных реквизитов актов от реквизитов сторон (Р26)."""

from __future__ import annotations

import pytest

from masker.detect.legal_references import (
    is_normative_act_adoption_date,
    is_public_legal_reference_type,
)
from masker.model import EntityType


@pytest.mark.parametrize(
    "text",
    (
        "постановлением Правительства Российской Федерации от 15 апреля 2014",
        "распоряжения Правительства Российской Федерации от 23 января 2024",
        "пункта 2 части 1 статьи 93 Федерального закона от 5 апреля 2013",
        "приказом Министерства здравоохранения от 10 мая 2024",
    ),
)
def test_act_kind_and_direct_from_bind_adoption_date(text: str) -> None:
    """Р26: только связка вида акта с «от» даёт иммунитет его дате."""
    assert is_normative_act_adoption_date(text, text.rindex("от") + len("от "))


def test_contract_date_is_not_hidden_by_an_earlier_act_reference() -> None:
    """Иммунитет акта не распространяется на следующую дату договора."""
    text = "Федеральным законом установлено правило. Договор от 7 февраля 2024"
    assert not is_normative_act_adoption_date(text, text.rindex("от") + len("от "))


def test_federal_law_type_is_public_reference() -> None:
    """Р26: номер закона не формирует замену в выходном документе."""
    assert is_public_legal_reference_type(EntityType.FEDERAL_LAW)
    assert not is_public_legal_reference_type(EntityType.CONTRACT_NUMBER)
