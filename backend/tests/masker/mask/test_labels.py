import re

import pytest

from masker.mask.labels import (
    HUMAN_TYPE_LABELS,
    MARKER_TYPE_LABELS,
    assign_compact_labels,
    assign_type_codes,
    compose_canonical_label,
    compose_marker,
    human_type_label,
    humanize_role,
    marker_ladder,
    type_marker_label,
)
from masker.model import EntityType, MaskGroup


def test_every_entity_type_has_marker_label() -> None:
    """Добавление типа без метки роняет тест — единственная защита от KeyError в плане."""
    assert set(MARKER_TYPE_LABELS) == set(EntityType)


def test_marker_labels_are_upper_case_cyrillic_without_spaces() -> None:
    """Пробел, точка или произвольная латиница в метке ломают читаемость."""
    for label in MARKER_TYPE_LABELS.values():
        assert label == label.upper()
        assert " " not in label
        assert "." not in label
        # Допускаем дефис внутри метки для составных меток («СУММА-ДОГОВОРА»),
        # но не в начале/конце — иначе маркер «[-ИНН]» или «[ИНН-]» сломан.
        assert re.fullmatch(r"(?:IP-)?(?:[А-ЯЁ][А-ЯЁ-]*[А-ЯЁ]|[А-ЯЁ])", label), label


def test_type_marker_label_matches_dict() -> None:
    assert type_marker_label(EntityType.INN) == "ИНН"
    assert type_marker_label(EntityType.ORG_NAME) == "ОРГАНИЗАЦИЯ"
    assert type_marker_label(EntityType.POWER_OF_ATTORNEY_NUMBER) == "НОМЕР-ДОВЕРЕННОСТИ"
    assert type_marker_label(EntityType.IP_ADDRESS) == "IP-АДРЕС"


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


# ── план М4: человекочитаемая каноническая форма ────────────────────────────


def test_every_entity_type_has_human_label() -> None:
    """Добавление типа без человеческой метки роняет тест — та же защита,
    что и у `MARKER_TYPE_LABELS`, только для читаемого маркера."""
    assert set(HUMAN_TYPE_LABELS) == set(EntityType)


def test_human_type_labels_are_not_screaming_caps() -> None:
    """Настоящие аббревиатуры (ИНН, КПП...) капсом — это нормально; составные
    названия — обычным регистром, не капсом с дефисами, как в `MARKER_TYPE_LABELS`."""
    for label in HUMAN_TYPE_LABELS.values():
        assert "-" not in label or label == "IP-адрес"
        # Не вся строка в капсе — либо это одно слово-аббревиатура без строчных
        # букв вовсе (ИНН), либо обычное предложение с одной заглавной буквы.
        assert (
            label.isupper()
            or label == "IP-адрес"
            or (label[0].isupper() and label[1:] == label[1:].lower())
        )


def test_human_type_label_matches_dict() -> None:
    assert human_type_label(EntityType.INN) == "ИНН"
    assert human_type_label(EntityType.ORG_NAME) == "Организация"
    assert human_type_label(EntityType.CONTRACT_NUMBER) == "Номер договора"
    assert human_type_label(EntityType.DATE) == "Дата договора"
    assert human_type_label(EntityType.POWER_OF_ATTORNEY_NUMBER) == "Номер доверенности"
    assert human_type_label(EntityType.IP_ADDRESS) == "IP-адрес"


@pytest.mark.parametrize(
    "role_label,expected",
    [
        ("", ""),
        ("ЗАКАЗЧИК", "Заказчик"),
        ("ФИНАНСОВОГО-УПРАВЛЯЮЩЕГО", "Финансового управляющего"),
        ("СТОРОНА-2", "Сторона 2"),
    ],
)
def test_humanize_role_variants(role_label: str, expected: str) -> None:
    assert humanize_role(role_label) == expected


def test_compose_canonical_label_org_name_with_role_shows_role_alone() -> None:
    """Организация — сама сторона договора: рядом с ролью тип избыточен."""
    assert compose_canonical_label("ЗАКАЗЧИК", EntityType.ORG_NAME, None) == "[Заказчик]"


def test_compose_canonical_label_person_with_role_shows_role_and_type() -> None:
    assert (
        compose_canonical_label("ПОСТАВЩИК", EntityType.PERSON, None) == "[Поставщик Представитель]"
    )


def test_compose_canonical_label_without_role_is_bare_type() -> None:
    assert compose_canonical_label("", EntityType.CONTRACT_NUMBER, None) == "[Номер договора]"
    assert compose_canonical_label("", EntityType.DATE, None) == "[Дата договора]"


def test_compose_canonical_label_number_only_when_given() -> None:
    """Номер добавляется, только когда вызывающий код (`PlanAgent`) решил, что
    сущностей такого рода больше одной — сама функция этого не решает."""
    assert compose_canonical_label("ПОСТАВЩИК", EntityType.INN, None) == "[Поставщик ИНН]"
    assert compose_canonical_label("ПОСТАВЩИК", EntityType.INN, 2) == "[Поставщик ИНН 2]"


def test_compose_canonical_label_two_roles_never_collapse() -> None:
    supplier = compose_canonical_label("ПОСТАВЩИК", EntityType.PERSON, None)
    buyer = compose_canonical_label("ПОКУПАТЕЛЬ", EntityType.PERSON, None)
    assert supplier != buyer


# ── план М1/М4: лестница отступления маркера ────────────────────────────────


def _group(
    *,
    marker: str,
    role_label: str = "",
    number: int = 1,
    compact_label: str = "[Ф1]",
    entity_type: str = EntityType.PERSON,
    canonical_label: str | None = None,
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
        canonical_label=canonical_label if canonical_label is not None else marker,
        compact_label=compact_label,
    )


def test_marker_ladder_full_sequence_with_role_and_number() -> None:
    """`marker` — машинный, только чтобы вычислить show_number/type;
    `canonical_label` — человеческая форма, план М4, реально печатается."""
    group = _group(
        marker="[ПОСТАВЩИК-ФИО-1]",
        role_label="ПОСТАВЩИК",
        number=1,
        canonical_label="[Поставщик Представитель 1]",
    )
    ladder = marker_ladder(group)
    assert ladder == [
        ("[Поставщик Представитель 1]", ""),
        ("[Поставщик 1]", "role_only"),
        ("[Ф1]", "compact"),
        ("[Представитель]", "type_only"),
        ("", "blank"),
    ]


def test_marker_ladder_without_role_skips_role_rungs() -> None:
    group = _group(
        marker="[ИНН]",
        role_label="",
        compact_label="[И1]",
        entity_type=EntityType.INN,
        canonical_label="[ИНН]",
    )
    ladder = marker_ladder(group)
    assert ladder == [
        ("[ИНН]", ""),
        ("[И1]", "compact"),
        ("[ИНН]", "type_only"),
        ("", "blank"),
    ]


def test_marker_ladder_type_only_rung_dropped_when_equal_to_canonical() -> None:
    """У сущности без роли и без сокращения ступень «только тип» совпадает с
    канонической — пробовать её отдельно бессмысленно, рунг пропускается."""
    group = _group(
        marker="[ИНН]",
        role_label="",
        compact_label="",
        entity_type=EntityType.INN,
        canonical_label="[ИНН]",
    )
    ladder = marker_ladder(group)
    assert ladder == [("[ИНН]", ""), ("", "blank")]


def test_marker_ladder_two_roles_never_collapse_to_same_compact_rung() -> None:
    """Инвариант приёмки: у двух групп с разными ролями рунг «compact»
    (не первая, «полная» ступень) не совпадает."""
    supplier = _group(
        marker="[ПОСТАВЩИК-ФИО-1]",
        role_label="ПОСТАВЩИК",
        compact_label="[Ф1]",
        canonical_label="[Поставщик Представитель]",
    )
    buyer = _group(
        marker="[ПОКУПАТЕЛЬ-ФИО-1]",
        role_label="ПОКУПАТЕЛЬ",
        compact_label="[Ф2]",
        canonical_label="[Покупатель Представитель]",
    )
    supplier_compact = next(text for text, reason in marker_ladder(supplier) if reason == "compact")
    buyer_compact = next(text for text, reason in marker_ladder(buyer) if reason == "compact")
    assert supplier_compact != buyer_compact


def test_marker_ladder_two_roles_never_collapse_to_same_role_only_rung() -> None:
    """Тот же инвариант для ступени «только роль» — она сама и есть роль,
    поэтому две разные роли по определению не совпадают."""
    supplier = _group(
        marker="[ПОСТАВЩИК-ФИО-1]",
        role_label="ПОСТАВЩИК",
        canonical_label="[Поставщик Представитель]",
    )
    buyer = _group(
        marker="[ПОКУПАТЕЛЬ-ФИО-1]",
        role_label="ПОКУПАТЕЛЬ",
        canonical_label="[Покупатель Представитель]",
    )
    supplier_role_only = next(
        text for text, reason in marker_ladder(supplier) if reason == "role_only"
    )
    buyer_role_only = next(text for text, reason in marker_ladder(buyer) if reason == "role_only")
    assert supplier_role_only != buyer_role_only
