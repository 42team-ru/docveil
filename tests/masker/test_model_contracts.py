import dataclasses
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from itertools import permutations

import pytest

from masker.model import (
    CRITICAL_TYPES,
    DECISION_PRECEDENCE,
    KEEP_CRITICAL_OPTION,
    KEEP_OPTION,
    MASK_OPTION,
    Action,
    Anchor,
    Decision,
    DecisionSource,
    Entity,
    EntityType,
    Leak,
    MaskGroup,
    MaskPlan,
    PolicyQuestion,
    Replacement,
    SkippedRef,
    Source,
    ValidationReport,
    is_critical,
)


def test_criticality_has_one_source_of_truth() -> None:
    assert is_critical(EntityType.INN)
    assert not is_critical(EntityType.PHONE)
    assert {kind for kind in EntityType if is_critical(kind)} == CRITICAL_TYPES


def test_decision_is_frozen_and_holds_a_single_ref_verdict() -> None:
    decision = Decision(
        ref="E1",
        action=Action.MASK,
        decided_by=DecisionSource.CRITICAL_GUARD,
        question_id="",
        reason="критичный тип",
    )
    assert decision.ref == "E1"
    with pytest.raises(FrozenInstanceError):
        decision.action = Action.KEEP  # type: ignore[misc]


def test_decision_precedence_has_exactly_six_sources_in_the_specified_order() -> None:
    expected = (
        DecisionSource.CRITICAL_GUARD,
        DecisionSource.ENTITY,
        DecisionSource.PROFILE,
        DecisionSource.TYPE,
        DecisionSource.JUDGE,
        DecisionSource.DEFAULT,
    )
    assert expected == DECISION_PRECEDENCE
    assert len(DECISION_PRECEDENCE) == 6
    assert len(set(DECISION_PRECEDENCE)) == 6


@pytest.mark.parametrize(
    "candidate",
    [
        permutation
        for permutation in permutations(
            (
                DecisionSource.CRITICAL_GUARD,
                DecisionSource.ENTITY,
                DecisionSource.PROFILE,
                DecisionSource.TYPE,
                DecisionSource.JUDGE,
                DecisionSource.DEFAULT,
            )
        )
        if permutation
        != (
            DecisionSource.CRITICAL_GUARD,
            DecisionSource.ENTITY,
            DecisionSource.PROFILE,
            DecisionSource.TYPE,
            DecisionSource.JUDGE,
            DecisionSource.DEFAULT,
        )
    ],
)
def test_decision_precedence_fails_on_any_other_permutation(
    candidate: tuple[str, ...],
) -> None:
    """DECISION_PRECEDENCE обязан не совпасть ни с какой другой перестановкой."""
    assert candidate != DECISION_PRECEDENCE


def test_entity_precedes_profile_and_type() -> None:
    entity_priority = DECISION_PRECEDENCE.index(DecisionSource.ENTITY)
    profile_priority = DECISION_PRECEDENCE.index(DecisionSource.PROFILE)
    type_priority = DECISION_PRECEDENCE.index(DecisionSource.TYPE)
    assert entity_priority < profile_priority < type_priority


def test_policy_question_is_hashable_and_carries_no_refs() -> None:
    question = PolicyQuestion(
        id="TYPE-inn",
        kind="type",
        target="inn",
        title="ИНН",
        prompt="Маскировать все ИНН (найдено 3)?",
        options=(MASK_OPTION,),
        default=MASK_OPTION,
        critical=True,
        found=3,
        by_type=(),
        samples=("3662103003",),
        anchors=(),
        linked=(),
        role_title="",
    )
    assert hash(question) == hash(question)
    assert not hasattr(question, "refs")


def test_keep_critical_option_is_distinct_from_keep_option() -> None:
    assert KEEP_CRITICAL_OPTION != KEEP_OPTION
    assert MASK_OPTION != KEEP_OPTION


def test_judge_agent_imports_options_instead_of_redefining_them() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import ast, sys; sys.exit(0)"],
        check=False,
    )
    assert result.returncode == 0
    grep = subprocess.run(
        ["grep", "-n", "MASK_OPTION", "src/masker/judge/agent.py"],
        capture_output=True,
        text=True,
        cwd=__file__.rsplit("/tests/", 1)[0],
        check=False,
    )
    lines = grep.stdout.splitlines()
    assert lines, "MASK_OPTION должен встречаться в judge/agent.py как импорт"
    assert not any(line.split(":", 1)[1].lstrip().startswith("MASK_OPTION =") for line in lines)


def _sample_entity() -> Entity:
    return Entity(
        type=EntityType.INN,
        text="3662103003",
        segment_order=0,
        start=0,
        end=10,
        source=Source.RULE,
    )


def _sample_anchor() -> Anchor:
    return Anchor(fmt="docx", locator=("body", 0), label="абзац 1")


def _sample_replacement() -> Replacement:
    return Replacement(
        ref="E1",
        entity=_sample_entity(),
        marker="[ПОСТАВЩИК-ИНН]",
        group_id="G1",
        profile_id="P1",
        anchor=_sample_anchor(),
    )


def _sample_group() -> MaskGroup:
    return MaskGroup(
        id="G1",
        key="inn:3662103003",
        type=EntityType.INN,
        marker="[ПОСТАВЩИК-ИНН]",
        profile_id="P1",
        role_label="ПОСТАВЩИК",
        number=1,
        refs=("E1",),
        sample="3662103003",
    )


def _sample_skipped() -> SkippedRef:
    return SkippedRef(ref="E2", type=EntityType.PERSON, reason="type_not_requested")


def _sample_plan() -> MaskPlan:
    return MaskPlan(
        replacements=(_sample_replacement(),),
        groups=(_sample_group(),),
        skipped=(_sample_skipped(),),
        requested_types=("inn",),
    )


def _sample_leak() -> Leak:
    return Leak(
        kind="raw",
        artifact="redacted.docx",
        part="word/document.xml",
        entity_type="inn",
        value="3662103003",
        ref="E1",
        group_id="G1",
        detail="исходная строка найдена побайтово",
    )


def _sample_validation_report() -> ValidationReport:
    return ValidationReport(
        leaked=(_sample_leak(),),
        residual=(),
        checked_artifacts=("redacted.docx",),
        checked_parts=("word/document.xml",),
        ok=False,
    )


@pytest.mark.parametrize(
    "instance,frozen_attr,frozen_value",
    [
        (_sample_group(), "marker", "[X]"),
        (_sample_replacement(), "marker", "[X]"),
        (_sample_skipped(), "reason", "kept"),
        (_sample_plan(), "requested_types", ()),
        (_sample_leak(), "kind", "detector"),
        (_sample_validation_report(), "ok", True),
    ],
)
def test_mask_plan_is_frozen_and_ordered(
    instance: object, frozen_attr: str, frozen_value: object
) -> None:
    """`MaskPlan` и все его элементы неизменяемы, коллекции — кортежи.

    Без `frozen=True, slots=True` согласованность псевдонимов (T1.6) ничем
    не защищена от случайной мутации плана между Plan и Render/Validate.
    """
    assert dataclasses.is_dataclass(instance)
    with pytest.raises(FrozenInstanceError):
        setattr(instance, frozen_attr, frozen_value)
    # slots=True → нет __dict__, произвольный новый атрибут не добавить.
    with pytest.raises(AttributeError):
        _ = instance.__dict__


def test_mask_plan_collection_fields_are_tuples() -> None:
    plan = _sample_plan()
    assert isinstance(plan.replacements, tuple)
    assert isinstance(plan.groups, tuple)
    assert isinstance(plan.skipped, tuple)
    assert isinstance(plan.requested_types, tuple)
    group = plan.groups[0]
    assert isinstance(group.refs, tuple)
    report = _sample_validation_report()
    assert isinstance(report.leaked, tuple)
    assert isinstance(report.residual, tuple)
    assert isinstance(report.checked_artifacts, tuple)
    assert isinstance(report.checked_parts, tuple)


def test_replacement_exposes_entity_and_marker() -> None:
    """Контракт `eval.py:207` (`repl.entity.type.value`, `repl.entity.text`).

    Переименование этих полей молча ломает ещё не подключённую метрику —
    тест защищает именно имена, а не только наличие данных.
    """
    repl = _sample_replacement()
    assert repl.entity.type.value == "inn"
    assert repl.entity.text == "3662103003"
    assert repl.marker == "[ПОСТАВЩИК-ИНН]"


def test_mask_plan_round_trips_through_json_via_asdict() -> None:
    """Отчёт и сериализатор графа опираются на `dataclasses.asdict` + json.

    Тест не про сам план как таковой, а про то, что вложенные `Entity`
    (не frozen) и `EntityType` (StrEnum) не ломают сериализацию, которую
    предполагает раздел «Детерминизм» плана T1.6/T1.8.
    """
    plan = _sample_plan()
    payload = dataclasses.asdict(plan)
    dumped = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    assert "[ПОСТАВЩИК-ИНН]" in dumped
    assert "type_not_requested" in dumped


def test_leak_defaults_are_empty_strings() -> None:
    leak = Leak(
        kind="detector",
        artifact="redacted.docx",
        part="",
        entity_type="person",
        value="Иванов И.И.",
    )
    assert leak.ref == ""
    assert leak.group_id == ""
    assert leak.detail == ""
