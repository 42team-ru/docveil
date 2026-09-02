import json
from pathlib import Path
from typing import Any

from masker.detect.agent import DetectAgent
from masker.graph.serde import (
    decisions_from_dicts,
    decisions_to_dicts,
    plan_from_dict,
    plan_to_dict,
    policy_questions_from_dicts,
    policy_questions_to_dicts,
    profiles_from_dicts,
    profiles_to_dicts,
)
from masker.graph.state import State
from masker.ingest.docx_ingest import ingest_docx
from masker.mask import PlanAgent
from masker.model import Action, Anchor, Decision, DecisionSource, EntityType, PolicyQuestion
from masker.profile import ProfileAgent
from masker.refs import EntityIndex, entity_sort_key

FIXTURES = Path(__file__).parents[3] / "fixtures" / "labeled"

_JSON_SCALARS = (str, int, float, bool, type(None))


def test_profile_serde_round_trip_is_json_stable() -> None:
    document = ingest_docx(FIXTURES / "contract_01.docx")
    profiles = ProfileAgent().profile(document, DetectAgent().detect(document)).profiles
    serialized = profiles_to_dicts(profiles)
    assert profiles_from_dicts(serialized) == profiles
    assert json.dumps(serialized, ensure_ascii=False, sort_keys=True) == json.dumps(
        profiles_to_dicts(profiles_from_dicts(serialized)), ensure_ascii=False, sort_keys=True
    )


def test_plan_serde_round_trip_restores_tuples_and_skipped() -> None:
    """``plan_from_dict(plan_to_dict(p)) == p`` — T1.10, шаг 4, критерий приёмки."""
    document = ingest_docx(FIXTURES / "contract_01.docx")
    entities = DetectAgent().detect(document).entities
    found_types = sorted({entity.type.value for entity in entities})
    assert len(found_types) > 1, "фикстура должна содержать хотя бы два типа сущностей"
    requested_types = frozenset(EntityType(value) for value in found_types[:-1])

    index = EntityIndex(entities)
    ordered = sorted(entities, key=entity_sort_key)
    kept_entity = next(entity for entity in ordered if entity.type in requested_types)
    kept_ref = index.ref(kept_entity)

    plan = PlanAgent().plan(
        document,
        entities,
        requested_types=requested_types,
        actions={kept_ref: Action.KEEP},
    )
    reasons = {item.reason for item in plan.skipped}
    assert "type_not_requested" in reasons
    assert "kept" in reasons
    assert plan.groups
    assert plan.replacements

    serialized = plan_to_dict(plan)
    restored = plan_from_dict(serialized)

    assert restored == plan
    assert isinstance(restored.requested_types, tuple)
    assert isinstance(restored.groups, tuple)
    assert isinstance(restored.replacements, tuple)
    assert isinstance(restored.skipped, tuple)
    assert json.dumps(serialized, ensure_ascii=False, sort_keys=True) == json.dumps(
        plan_to_dict(restored), ensure_ascii=False, sort_keys=True
    )


def _sample_policy_questions() -> list[PolicyQuestion]:
    return [
        PolicyQuestion(
            id="TYPE-inn",
            kind="type",
            target="inn",
            title="ИНН",
            prompt="Маскировать все «ИНН» (найдено 3)?",
            options=("маскировать",),
            default="маскировать",
            critical=True,
            found=3,
            by_type=(),
            samples=("3662103003", "7743013902"),
            anchors=(Anchor(fmt="docx", locator=("body", 0), label="абзац 1"),),
            linked=(),
            role_title="",
        ),
        PolicyQuestion(
            id="PROFILE-P3",
            kind="profile",
            target="P3",
            title="СТОРОНА-3",
            prompt="Маскировать реквизиты субъекта СТОРОНА-3 (найдено сущностей: 4)?",
            options=("маскировать", "оставить"),
            default="маскировать",
            critical=False,
            found=4,
            by_type=(("inn", 1), ("person", 1)),
            samples=("Иванов Иван Иванович",),
            anchors=(),
            linked=("P4", "P5"),
            role_title="Поставщик",
        ),
    ]


def test_policy_questions_round_trip_is_json_stable() -> None:
    questions = _sample_policy_questions()
    serialized = policy_questions_to_dicts(questions)
    assert policy_questions_from_dicts(serialized) == questions
    assert json.dumps(serialized, ensure_ascii=False, sort_keys=True) == json.dumps(
        policy_questions_to_dicts(policy_questions_from_dicts(serialized)),
        ensure_ascii=False,
        sort_keys=True,
    )


def _sample_decisions() -> tuple[list[Decision], dict[str, list[Decision]]]:
    decisions = [
        Decision("E1", Action.MASK, DecisionSource.CRITICAL_GUARD, "", "критичный тип"),
        Decision("E2", Action.KEEP, DecisionSource.TYPE, "TYPE-phone", "тип отключён человеком"),
    ]
    overridden = {
        "E1": [],
        "E2": [Decision("E2", Action.MASK, DecisionSource.JUDGE, "", "уверенность достаточна")],
    }
    return decisions, overridden


def test_decisions_round_trip_includes_overridden() -> None:
    decisions, overridden = _sample_decisions()
    serialized = decisions_to_dicts(decisions, overridden)
    restored_decisions, restored_overridden = decisions_from_dicts(serialized)
    assert restored_decisions == decisions
    assert restored_overridden == overridden
    assert json.dumps(serialized, ensure_ascii=False, sort_keys=True) == json.dumps(
        decisions_to_dicts(restored_decisions, restored_overridden),
        ensure_ascii=False,
        sort_keys=True,
    )


def test_decision_serde_tolerates_ref_from_foreign_namespace() -> None:
    """``H*`` — зарезервированное пространство ручной разметки (раздел 4 плана T1.5.1)."""
    decisions = [Decision("H1", Action.MASK, DecisionSource.ENTITY, "PII-H1", "вручную помечено")]
    serialized = decisions_to_dicts(decisions, {})
    restored_decisions, restored_overridden = decisions_from_dicts(serialized)
    assert restored_decisions == decisions
    assert restored_overridden == {"H1": []}


def _walk_json_safe(value: Any) -> None:
    if isinstance(value, _JSON_SCALARS):
        return
    if isinstance(value, list):
        for item in value:
            _walk_json_safe(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            _walk_json_safe(item)
        return
    raise AssertionError(f"в State обнаружен не-JSON-объект: {value!r}")


def test_state_holds_no_dataclasses() -> None:
    questions = _sample_policy_questions()
    decisions, overridden = _sample_decisions()
    state: State = {
        "meta": {"path": "contract.docx"},
        "options": {"types": ["inn"], "interactive": True},
        "policy_questions": policy_questions_to_dicts(questions),
        "decisions": {"mode": "interactive", "critical_unmasked": []},
        "final_actions": decisions_to_dicts(decisions, overridden),
    }
    for value in state.values():
        _walk_json_safe(value)
    dumped = json.dumps(state, ensure_ascii=False, sort_keys=True)
    assert json.dumps(json.loads(dumped), ensure_ascii=False, sort_keys=True) == dumped
