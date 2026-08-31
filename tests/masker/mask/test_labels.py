import re

import pytest

from masker.mask.labels import MARKER_TYPE_LABELS, compose_marker, type_marker_label
from masker.model import EntityType


def test_every_entity_type_has_marker_label() -> None:
    """Добавление типа без метки роняет тест — единственная защита от KeyError в плане."""
    assert set(MARKER_TYPE_LABELS) == set(EntityType)


def test_marker_labels_are_upper_case_cyrillic_without_spaces() -> None:
    """Пробел, точка или латиница в метке ломают читаемость `[A-B-C]`."""
    for label in MARKER_TYPE_LABELS.values():
        assert label == label.upper()
        assert " " not in label
        assert "." not in label
        assert re.fullmatch(r"[А-ЯЁ]+", label), label


def test_type_marker_label_matches_dict() -> None:
    assert type_marker_label(EntityType.INN) == "ИНН"
    assert type_marker_label(EntityType.ORG_NAME) == "ОРГАНИЗАЦИЯ"


@pytest.mark.parametrize(
    "role_label,type_label,number,expected",
    [
        ("ПОСТАВЩИК", "ИНН", None, "[ПОСТАВЩИК-ИНН]"),
        ("ПОСТАВЩИК", "ФИО", 2, "[ПОСТАВЩИК-ФИО-2]"),
        ("", "ИНН", 1, "[ИНН-1]"),
    ],
)
def test_compose_marker_variants(
    role_label: str, type_label: str, number: int | None, expected: str
) -> None:
    assert compose_marker(role_label, type_label, number) == expected


def test_compose_marker_without_role_and_number_is_bare_type() -> None:
    assert compose_marker("", "ДАТА", None) == "[ДАТА]"
