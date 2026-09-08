import re

import pytest

from masker.mask.labels import (
    MARKER_TYPE_LABELS,
    assign_compact_labels,
    assign_type_codes,
    compose_marker,
    marker_ladder,
    type_marker_label,
)
from masker.model import EntityType, MaskGroup


def test_every_entity_type_has_marker_label() -> None:
    """Добавление типа без метки роняет тест — единственная защита от KeyError в плане."""
    assert set(MARKER_TYPE_LABELS) == set(EntityType)


def test_marker_labels_are_upper_case_cyrillic_without_spaces() -> None:
    """Пробел, точка или латиница в метке ломают читаемость `[A-B-C]`."""
    for label in MARKER_TYPE_LABELS.values():
        assert label == label.upper()
        assert " " not in label
        assert "." not in label
        # Допускаем дефис внутри метки для составных меток («СУММА-ДОГОВОРА»),
        # но не в начале/конце — иначе маркер «[-ИНН]» или «[ИНН-]» сломан.
        assert re.fullmatch(r"[А-ЯЁ][А-ЯЁ-]*[А-ЯЁ]|[А-ЯЁ]", label), label


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


# ── план М1: код типа для компактной метки ─────────────────────────────────


def test_assign_type_codes_grows_prefix_on_collision() -> None:
    """`ОГРН` и `ОРГАНИЗАЦИЯ` оба начинаются на «О» — код обязан вырасти,
    а не столкнуться на однобуквенном варианте."""
    codes = assign_type_codes([EntityType.OGRN, EntityType.ORG_NAME])
    assert codes[EntityType.OGRN] != codes[EntityType.ORG_NAME]
    assert len(set(codes.values())) == len(codes)


def test_assign_type_codes_is_deterministic_regardless_of_input_order() -> None:
    """Порядок обхода — по id типа, а не по порядку появления в документе:
    два прогона с сущностями в разном порядке дают одинаковые коды."""
    forward = assign_type_codes([EntityType.INN, EntityType.PERSON, EntityType.ORG_NAME])
    backward = assign_type_codes([EntityType.ORG_NAME, EntityType.PERSON, EntityType.INN])
    assert forward == backward


def test_assign_type_codes_single_letter_for_non_colliding_type() -> None:
    assert assign_type_codes([EntityType.PERSON])[EntityType.PERSON] == "Ф"


# ── план М1: компактная метка группы, глобально уникальная ────────────────


def test_assign_compact_labels_gives_different_roles_different_labels() -> None:
    """Два профиля с разными ролями (оба — первая группа ФИО в своей паре)
    не должны схлопнуться в одинаковый `[Ф1]` — см. критерий приёмки М1."""
    labels = assign_compact_labels(
        [("supplier_g1", EntityType.PERSON), ("buyer_g1", EntityType.PERSON)]
    )
    assert labels["supplier_g1"] != labels["buyer_g1"]
    assert labels["supplier_g1"] == "[Ф1]"
    assert labels["buyer_g1"] == "[Ф2]"


def test_assign_compact_labels_numbers_sequentially_per_type() -> None:
    labels = assign_compact_labels(
        [
            ("g1", EntityType.PERSON),
            ("g2", EntityType.INN),
            ("g3", EntityType.PERSON),
        ]
    )
    assert labels == {"g1": "[Ф1]", "g2": "[И1]", "g3": "[Ф2]"}


# ── план М1: лестница отступления маркера ──────────────────────────────────


def _group(
    *,
    marker: str,
    role_label: str = "",
    number: int = 1,
    compact_label: str = "[Ф1]",
    entity_type: str = EntityType.PERSON,
) -> MaskGroup:
    return MaskGroup(
        id="G1",
        key="person:иванов",
        type=entity_type,
        marker=marker,
        profile_id="P1" if role_label else "",
        role_label=role_label,
        number=number,
        refs=("E1",),
        sample="Иванов",
        canonical_label=marker,
        compact_label=compact_label,
    )


def test_marker_ladder_full_sequence_with_role_and_number() -> None:
    group = _group(marker="[ПОСТАВЩИК-ФИО-1]", role_label="ПОСТАВЩИК", number=1)
    ladder = marker_ladder(group)
    assert ladder == [
        ("[ПОСТАВЩИК-ФИО-1]", ""),
        ("[ПОСТ-ФИО-1]", "role_short"),
        ("[П-ФИО-1]", "role_initial"),
        ("[Ф1]", "compact"),
        ("ФИО", "type_only"),
        ("", "blank"),
    ]


def test_marker_ladder_without_role_skips_role_rungs() -> None:
    group = _group(marker="[ИНН]", role_label="", compact_label="[И1]", entity_type=EntityType.INN)
    ladder = marker_ladder(group)
    assert ladder == [
        ("[ИНН]", ""),
        ("[И1]", "compact"),
        ("ИНН", "type_only"),
        ("", "blank"),
    ]


def test_marker_ladder_two_roles_never_collapse_to_same_compact_rung() -> None:
    """Инвариант приёмки: у двух групп с разными ролями рунг «compact»
    (третья ступень с сохранённым номером) не совпадает."""
    supplier = _group(marker="[ПОСТАВЩИК-ФИО-1]", role_label="ПОСТАВЩИК", compact_label="[Ф1]")
    buyer = _group(marker="[ПОКУПАТЕЛЬ-ФИО-1]", role_label="ПОКУПАТЕЛЬ", compact_label="[Ф2]")
    supplier_compact = next(text for text, reason in marker_ladder(supplier) if reason == "compact")
    buyer_compact = next(text for text, reason in marker_ladder(buyer) if reason == "compact")
    assert supplier_compact != buyer_compact
