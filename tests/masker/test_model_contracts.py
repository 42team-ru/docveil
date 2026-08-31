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
    Decision,
    DecisionSource,
    EntityType,
    PolicyQuestion,
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
