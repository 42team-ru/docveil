"""Тесты `PlanAgent` — ядро T1.6 (docs/plans/T1.6-T1.8-plan-validate.md, шаг 4)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from masker.mask.agent import PlanAgent
from masker.model import (
    Action,
    Anchor,
    Document,
    Entity,
    EntityType,
    Profile,
    ProfileMember,
    Segment,
    Source,
)
from masker.refs import EntityIndex


def _document(count: int) -> Document:
    """Документ из `count` пустых сегментов — тексту здесь верить не нужно:
    `PlanAgent` берёт из документа только якоря по `segment_order`."""
    segments = [
        Segment(
            text=f"сегмент {order}",
            anchor=Anchor(fmt="docx", locator=("body", order), label=f"абзац {order}"),
            order=order,
        )
        for order in range(count)
    ]
    return Document(path="doc.docx", fmt="docx", segments=segments)


def _entity(
    entity_type: EntityType,
    text: str,
    *,
    segment_order: int = 0,
    start: int = 0,
) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=segment_order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
    )


def _profile(
    profile_id: str, marker_label: str, members: list[Entity], index: EntityIndex
) -> Profile:
    return Profile(
        id=profile_id,
        members=[
            ProfileMember(
                entity=entity, anchor=Anchor(fmt="docx", locator=()), ref=index.ref(entity)
            )
            for entity in members
        ],
        marker_label=marker_label,
    )


def test_org_mentioned_five_times_in_three_spellings_gets_one_marker() -> None:
    spellings = [
        'ООО "Ромашка"',
        "ООО «Ромашка»",
        "Ромашка",
        'ООО "Ромашка"',
        "Ромашка",
    ]
    entities = [
        _entity(EntityType.ORG_NAME, text, segment_order=order)
        for order, text in enumerate(spellings)
    ]
    document = _document(len(entities))
    index = EntityIndex(entities)
    profiles = [_profile("P1", "ПОСТАВЩИК", entities, index)]

    plan = PlanAgent().plan(document, entities, profiles=profiles)

    assert len(plan.groups) == 1
    assert len(plan.replacements) == 5
    markers = {repl.marker for repl in plan.replacements}
    assert markers == {"[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]"}
    assert plan.groups[0].marker == "[ПОСТАВЩИК-ОРГАНИЗАЦИЯ]"
    assert plan.groups[0].refs == tuple(index.ref(entity) for entity in entities)


def test_two_runs_produce_identical_plan() -> None:
    """Порядок входного списка сущностей не должен влиять на план.

    Ловит перестановку: на вход подаётся список в обратном текстовом
    порядке, план всё равно строится по позиции первого вхождения в
    документе, а не по порядку обхода входного списка/словаря.
    """
    spellings = ["Первая ООО", "Вторая АО", "Первая ООО"]
    entities = [
        _entity(EntityType.ORG_NAME, text, segment_order=order)
        for order, text in enumerate(spellings)
    ]
    document = _document(len(entities))

    plan_forward = PlanAgent().plan(document, entities)
    plan_reversed = PlanAgent().plan(document, list(reversed(entities)))

    def dump(plan: object) -> str:
        return json.dumps(dataclasses.asdict(plan), sort_keys=True, default=str)

    assert dump(plan_forward) == dump(plan_reversed)
    # план не вырожденный: реально две разные группы, а не случайное совпадение
    assert len(plan_forward.groups) == 2


def test_contract_amount_preferred_over_money_for_same_selected_span() -> None:
    """Два классификатора одной суммы не создают две замены в рендере."""
    document = _document(1)
    amount = "1 500 рублей"
    entities = [
        _entity(EntityType.MONEY, amount),
        _entity(EntityType.CONTRACT_AMOUNT, amount),
    ]

    plan = PlanAgent().plan(document, entities)

    assert [(replacement.entity.type, replacement.marker) for replacement in plan.replacements] == [
        (EntityType.CONTRACT_AMOUNT, "[СУММА-ДОГОВОРА]"),
    ]


def test_money_remains_selectable_without_contract_amount() -> None:
    """Выбор общего типа не теряет сумму, классифицированную как цену договора."""
    document = _document(1)
    amount = "1 500 рублей"
    entities = [
        _entity(EntityType.MONEY, amount),
        _entity(EntityType.CONTRACT_AMOUNT, amount),
    ]

    plan = PlanAgent().plan(document, entities, requested_types=frozenset({EntityType.MONEY}))

    assert [(replacement.entity.type, replacement.marker) for replacement in plan.replacements] == [
        (EntityType.MONEY, "[СУММА]"),
    ]


def test_entity_without_profile_gets_marker_without_role() -> None:
    entities = [
        _entity(EntityType.DATE, "01.01.2024", segment_order=0),
        _entity(EntityType.DATE, "02.02.2024", segment_order=1),
    ]
    document = _document(len(entities))

    plan = PlanAgent().plan(document, entities)

    markers = sorted(repl.marker for repl in plan.replacements)
    assert markers == ["[ДАТА-1]", "[ДАТА-2]"]
    assert all(repl.profile_id == "" for repl in plan.replacements)
    assert all(group.role_label == "" for group in plan.groups)


def test_two_persons_of_one_party_get_numbered_markers() -> None:
    first = _entity(EntityType.PERSON, "Иванов Иван Иванович", segment_order=0)
    second = _entity(EntityType.PERSON, "Петров Пётр Петрович", segment_order=1)
    entities = [first, second]
    document = _document(len(entities))
    index = EntityIndex(entities)
    profiles = [_profile("P1", "ПОСТАВЩИК", entities, index)]

    plan = PlanAgent().plan(document, entities, profiles=profiles)

    markers = sorted(repl.marker for repl in plan.replacements)
    assert markers == ["[ПОСТАВЩИК-ФИО-1]", "[ПОСТАВЩИК-ФИО-2]"]


def test_single_group_in_bucket_has_no_number() -> None:
    entity = _entity(EntityType.INN, "3662103003", segment_order=0)
    entities = [entity]
    document = _document(len(entities))
    index = EntityIndex(entities)
    profiles = [_profile("P2", "ПОКУПАТЕЛЬ", entities, index)]

    plan = PlanAgent().plan(document, entities, profiles=profiles)

    assert plan.replacements[0].marker == "[ПОКУПАТЕЛЬ-ИНН]"
    assert plan.groups[0].number == 1


def test_requested_types_filter_moves_to_plan() -> None:
    inn = _entity(EntityType.INN, "3662103003", segment_order=0)
    person = _entity(EntityType.PERSON, "Иванов Иван Иванович", segment_order=1)
    entities = [inn, person]
    document = _document(len(entities))
    index = EntityIndex(entities)

    plan = PlanAgent().plan(document, entities, requested_types=frozenset({EntityType.INN}))

    assert len(plan.replacements) == 1
    assert plan.replacements[0].entity.type is EntityType.INN
    assert len(plan.skipped) == 1
    skipped = plan.skipped[0]
    assert skipped.ref == index.ref(person)
    assert skipped.type is EntityType.PERSON
    assert skipped.reason == "type_not_requested"


def test_keep_action_excludes_entity_from_plan() -> None:
    entity = _entity(EntityType.INN, "3662103003", segment_order=0)
    entities = [entity]
    document = _document(len(entities))
    index = EntityIndex(entities)
    ref = index.ref(entity)

    plan = PlanAgent().plan(document, entities, actions={ref: Action.KEEP})

    assert plan.replacements == ()
    assert len(plan.skipped) == 1
    assert plan.skipped[0].ref == ref
    assert plan.skipped[0].reason == "kept"


def test_missing_ref_in_actions_defaults_to_mask() -> None:
    """`actions` может быть неполным — ref без явного решения маскируется.

    Не входит в явную приёмку плана T1.6, но без теста поведение при
    неполном словаре `actions` осталось бы недокументированной веткой.
    """
    entity = _entity(EntityType.INN, "3662103003", segment_order=0)
    entities = [entity]
    document = _document(len(entities))

    plan = PlanAgent().plan(document, entities, actions={})

    assert len(plan.replacements) == 1
    assert plan.skipped == ()


def test_same_value_in_two_profiles_gets_two_markers() -> None:
    """Один и тот же ИНН, привязанный к двум разным профилям (аномалия
    входных данных), не должен схлопнуться в общий маркер: профиль входит
    в ключ бакета группы."""
    first = _entity(EntityType.INN, "3662103003", segment_order=0)
    second = _entity(EntityType.INN, "3662103003", segment_order=1)
    entities = [first, second]
    document = _document(len(entities))
    index = EntityIndex(entities)
    profiles = [
        _profile("P1", "ПОСТАВЩИК", [first], index),
        _profile("P2", "ПОКУПАТЕЛЬ", [second], index),
    ]

    plan = PlanAgent().plan(document, entities, profiles=profiles)

    markers = {repl.marker for repl in plan.replacements}
    assert markers == {"[ПОСТАВЩИК-ИНН]", "[ПОКУПАТЕЛЬ-ИНН]"}
    assert len(plan.groups) == 2


def test_entity_with_missing_segment_anchor_is_skipped_as_no_anchor() -> None:
    """Алгоритм заявлен как «без исключений»: сущность, чей `segment_order`
    не находится ни в одном сегменте документа, не роняет план `KeyError`,
    а уходит в `skipped` с причиной `no_anchor`."""
    entity = _entity(EntityType.INN, "3662103003", segment_order=5)
    entities = [entity]
    document = _document(0)  # ни одного сегмента — якоря нет ни для кого
    index = EntityIndex(entities)

    plan = PlanAgent().plan(document, entities)

    assert plan.replacements == ()
    assert len(plan.skipped) == 1
    assert plan.skipped[0].ref == index.ref(entity)
    assert plan.skipped[0].reason == "no_anchor"


def test_requested_types_none_matches_explicit_full_set() -> None:
    """Живая проверка решения из шага 4: ``requested_types=None`` и
    ``--types all`` (который CLI разворачивает в ``frozenset(EntityType)``,
    см. ``_parse_types``) обязаны давать одинаковый план. Расхождение здесь
    было бы багом, который в CLI незаметен — там ``--types`` всегда
    подставляет конкретное множество, `None` через CLI не достижим."""
    org = _entity(EntityType.ORG_NAME, "Ромашка", segment_order=0)
    date = _entity(EntityType.DATE, "01.01.2024", segment_order=1)
    entities = [org, date]
    document = _document(len(entities))

    plan_none = PlanAgent().plan(document, entities, requested_types=None)
    plan_all = PlanAgent().plan(document, entities, requested_types=frozenset(EntityType))

    def dump(plan: object) -> str:
        return json.dumps(dataclasses.asdict(plan), sort_keys=True, default=str)

    assert dump(plan_none) == dump(plan_all)


def test_requested_types_field_defaults_to_all_types_when_none() -> None:
    document = _document(0)
    plan = PlanAgent().plan(document, [])
    assert plan.requested_types == tuple(sorted(kind.value for kind in EntityType))


def test_requested_types_field_reflects_explicit_filter() -> None:
    document = _document(0)
    plan = PlanAgent().plan(
        document, [], requested_types=frozenset({EntityType.INN, EntityType.KPP})
    )
    assert plan.requested_types == ("inn", "kpp")


@pytest.mark.parametrize("reverse", [False, True])
def test_group_numbering_follows_first_occurrence_not_input_order(reverse: bool) -> None:
    """Номер группы — позиция первого вхождения в тексте, а не порядковый
    номер в списке, который агенту передали на вход."""
    later = _entity(EntityType.PERSON, "Второй Второй Второевич", segment_order=1)
    earlier = _entity(EntityType.PERSON, "Первый Первый Первеевич", segment_order=0)
    entities = [later, earlier] if reverse else [earlier, later]
    document = _document(2)
    index = EntityIndex(entities)
    profiles = [_profile("P1", "ПОСТАВЩИК", entities, index)]

    plan = PlanAgent().plan(document, entities, profiles=profiles)

    by_ref = {repl.ref: repl.marker for repl in plan.replacements}
    assert by_ref[index.ref(earlier)] == "[ПОСТАВЩИК-ФИО-1]"
    assert by_ref[index.ref(later)] == "[ПОСТАВЩИК-ФИО-2]"
