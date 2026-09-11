import pytest

from masker.detect.normalize import normalize_value
from masker.model import EntityType


def test_org_form_stripped() -> None:
    assert normalize_value(EntityType.ORG_NAME, "ООО «Ромашка»") == normalize_value(
        EntityType.ORG_NAME, "Ромашка"
    )


def test_person_key_is_case_insensitive() -> None:
    assert normalize_value(EntityType.PERSON, "Иванова") == normalize_value(
        EntityType.PERSON, "ИВАНОВА"
    )


@pytest.mark.parametrize(
    ("nominative", "oblique"),
    [
        ("Иванов Иван Иванович", "Иванова Ивана Ивановича"),
        ("Сидорова Анна Петровна", "Сидоровой Анны Петровны"),
        ("Петрова Мария Сергеевна", "Петровой Марии Сергеевны"),
        ("Кузнецов Пётр Алексеевич", "Кузнецова Петра Алексеевича"),
        ("Ильин Илья Юрьевич", "Ильина Ильи Юрьевича"),
    ],
)
def test_person_key_links_grammatical_cases(nominative: str, oblique: str) -> None:
    assert normalize_value(EntityType.PERSON, nominative) == normalize_value(
        EntityType.PERSON, oblique
    )


def test_initials_are_not_truncated() -> None:
    assert normalize_value(EntityType.PERSON, "И.И.") == "и.и."


def test_different_surnames_stay_different() -> None:
    assert normalize_value(EntityType.PERSON, "Иванов") != normalize_value(
        EntityType.PERSON, "Иванцов"
    )


def test_unknown_type_is_casefolded_and_whitespace_is_collapsed() -> None:
    assert normalize_value("unknown", "  Тест\tЗначение ") == "тест значение"


@pytest.mark.parametrize(
    ("entity_type", "text", "expected"),
    [
        (EntityType.POWER_OF_ATTORNEY_NUMBER, " МЧД-42 / А ", "мчд-42/а"),
        (EntityType.IP_ADDRESS, " 83.171.96.195 ", "83.171.96.195"),
    ],
)
def test_new_requisite_types_have_stable_normalized_keys(
    entity_type: EntityType, text: str, expected: str
) -> None:
    assert normalize_value(entity_type, text) == expected


def test_initials_key_is_the_same_regardless_of_word_order() -> None:
    assert normalize_value(EntityType.PERSON, "Атараев Б.М") == normalize_value(
        EntityType.PERSON, "Б.М. Атараев"
    )


def test_initials_key_is_the_same_regardless_of_dots_and_order() -> None:
    assert normalize_value(EntityType.PERSON, "И.И. Иванов") == normalize_value(
        EntityType.PERSON, "Иванов И.И."
    )
