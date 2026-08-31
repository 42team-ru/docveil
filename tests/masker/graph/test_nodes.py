"""Узлы графа: extract/detect/policy/finalize, фабрики RunDeps, роутер."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from masker.graph import nodes
from masker.graph.serde import entity_from_dict, policy_questions_from_dicts
from masker.graph.state import State
from masker.llm.fake import FakeProvider
from masker.model import EntityType

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_02_hard.docx"


def _extracted_state(*, types: list[str] | None = None, rules_only: bool = True) -> State:
    state: State = {
        "path": str(FIXTURE),
        "options": {"rules_only": rules_only, "types": types, "interactive": False},
    }
    state.update(nodes.extract_node(state))
    return state


def test_extract_node_fills_segments_fmt_and_meta() -> None:
    state = _extracted_state()

    assert state["fmt"] == "docx"
    assert state["segments"]
    assert state["meta"]["name"] == FIXTURE.name


def test_detect_node_filters_by_selected_types() -> None:
    state = _extracted_state(types=["inn"])

    state.update(nodes.detect_node(state))

    entities = [entity_from_dict(item) for item in state["entities"]]
    assert entities
    assert {entity.type for entity in entities} == {EntityType.INN}


def test_detect_node_finds_all_types_when_none_selected() -> None:
    state = _extracted_state(types=None)

    state.update(nodes.detect_node(state))

    entities = [entity_from_dict(item) for item in state["entities"]]
    assert {entity.type for entity in entities} == {
        EntityType.EMAIL,
        EntityType.INN,
        EntityType.PASSPORT,
        EntityType.SNILS,
    }


def _profiled_state() -> State:
    state = _extracted_state()
    state.update(nodes.detect_node(state))
    deps = nodes.RunDeps(llm=FakeProvider())
    state.update(nodes.make_profile_node(deps)(state))
    return state


def test_profile_node_factory_actually_calls_the_llm_provider() -> None:
    state = _extracted_state()
    state.update(nodes.detect_node(state))
    provider = FakeProvider()
    profile_node = nodes.make_profile_node(nodes.RunDeps(llm=provider))

    state.update(profile_node(state))

    assert provider.calls > 0
    assert state["profiles"]


def test_judge_node_factory_produces_verdicts_and_questions() -> None:
    state = _profiled_state()
    judge_node = nodes.make_judge_node(nodes.RunDeps())

    state.update(judge_node(state))

    assert state["verdicts"]
    assert isinstance(state["questions"], list)


def test_policy_node_builds_type_and_profile_questions() -> None:
    state = _profiled_state()
    state.update(nodes.make_judge_node(nodes.RunDeps())(state))

    state.update(nodes.policy_node(state))

    questions = policy_questions_from_dicts(state["policy_questions"])
    assert any(question.kind == "type" for question in questions)
    assert any(question.id == "TYPE-inn" for question in questions)


def _finalized_state() -> State:
    state = _profiled_state()
    deps = nodes.RunDeps()
    state.update(nodes.make_judge_node(deps)(state))
    state.update(nodes.policy_node(state))
    state["answers"] = {}
    state.update(nodes.apply_answers_node(state))
    state.update(nodes.finalize_node(state))
    return state


def test_finalize_node_has_exactly_one_record_per_ref_without_gaps_or_duplicates() -> None:
    state = _finalized_state()

    entities = [entity_from_dict(item) for item in state["entities"]]
    candidates = [entity_from_dict(item) for item in state.get("candidates", [])]
    expected_refs = {f"E{number}" for number in range(1, len(entities) + 1)} | {
        f"C{number}" for number in range(1, len(candidates) + 1)
    }

    refs = [item["ref"] for item in state["final_actions"]]

    assert sorted(refs) == sorted(expected_refs)
    assert len(refs) == len(set(refs))


def test_finalize_node_builds_decisions_summary() -> None:
    state = _finalized_state()

    decisions = state["decisions"]
    assert decisions["mode"] == "non_interactive"
    assert decisions["critical_unmasked"] == []
    assert isinstance(decisions["types"], list)
    assert isinstance(decisions["profiles"], list)


def test_needs_human_interactive_false_returns_apply_answers_even_with_questions() -> None:
    state: State = {
        "options": {"interactive": False},
        "policy_questions": [{"id": "TYPE-inn"}],
    }

    assert nodes.needs_human(state) == "apply_answers"


def test_needs_human_interactive_true_with_questions_returns_ask_human() -> None:
    state: State = {
        "options": {"interactive": True},
        "policy_questions": [{"id": "TYPE-inn"}],
    }

    assert nodes.needs_human(state) == "ask_human"


def test_needs_human_skips_ask_human_when_answers_already_present() -> None:
    state: State = {
        "options": {"interactive": True},
        "policy_questions": [{"id": "TYPE-inn"}],
        "answers": {"TYPE-inn": "маскировать"},
    }

    assert nodes.needs_human(state) == "apply_answers"


def test_needs_human_returns_apply_answers_when_no_questions_at_all() -> None:
    state: State = {"options": {"interactive": True}}

    assert nodes.needs_human(state) == "apply_answers"


def test_ask_human_node_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict[str, object]] = []

    def fake_interrupt(value: dict[str, object]) -> dict[str, object]:
        captured.append(value)
        return {"schema_version": 1, "answers": {"TYPE-inn": "маскировать"}}

    monkeypatch.setattr(nodes, "interrupt", fake_interrupt)
    state: State = {
        "meta": {"name": "contract.docx", "format": "docx"},
        "options": {"thread_id": "abc"},
        "policy_questions": [],
        "questions": [],
    }
    frozen = copy.deepcopy(state)

    first = nodes.ask_human_node(state)
    second = nodes.ask_human_node(state)

    assert state == frozen
    assert first == second == {"answers": {"TYPE-inn": "маскировать"}}
    assert list(tmp_path.iterdir()) == []
    assert captured[0] == captured[1]


def test_no_stdin_in_src() -> None:
    """Ворота не имеют права зависнуть в ожидании ввода — раздел 9 плана T1.5.1."""
    result = subprocess.run(
        ["grep", "-rn", "input(", "src/masker"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout == "", f"найден input() в src/masker: {result.stdout}"
