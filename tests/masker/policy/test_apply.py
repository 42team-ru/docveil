"""PolicyAgent.apply(): разрешение конфликтов и защита критичных типов."""

from __future__ import annotations

import random

from masker.detect.result import DetectionResult
from masker.model import (
    KEEP_CRITICAL_OPTION,
    KEEP_OPTION,
    MASK_OPTION,
    Action,
    Anchor,
    DecisionSource,
    Entity,
    EntityType,
    Profile,
    ProfileMember,
    Question,
    Source,
    Verdict,
)
from masker.policy.agent import PROFILE_UNASSIGNED, PolicyAgent
from masker.profile.agent import ProfileResult


def _entity(entity_type: EntityType, text: str, segment_order: int = 0, start: int = 0) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=segment_order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
    )


def _anchor(segment_order: int) -> Anchor:
    return Anchor(fmt="docx", locator=("body", segment_order), label=f"абзац {segment_order + 1}")


def _profile(profile_id: str, entities: list[Entity], refs: list[str]) -> Profile:
    return Profile(
        id=profile_id,
        members=[
            ProfileMember(entity, _anchor(entity.segment_order), ref)
            for entity, ref in zip(entities, refs, strict=True)
        ],
        marker_label=f"СТОРОНА-{profile_id[1:]}",
        confidence=1.0,
        source=Source.RULE,
    )


def _verdict(ref: str, action: Action, question_id: str = "") -> Verdict:
    return Verdict(ref=ref, action=action, confidence=1.0, reason="test", question_id=question_id)


def _profile_result(profiles: list[Profile], anchors: dict[int, Anchor]) -> ProfileResult:
    result = ProfileResult(profiles=profiles, blocks=[], unassigned=[], candidates=[])
    result.anchors = anchors
    return result


def test_type_keep_answer_masks_only_that_type() -> None:
    phone_1 = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    phone_2 = _entity(EntityType.PHONE, "+79007654321", 1, 0)
    inn = _entity(EntityType.INN, "3662103003", 2, 0)
    detection = DetectionResult([phone_1, phone_2, inn], [])
    profiles = _profile_result([], {0: _anchor(0), 1: _anchor(1), 2: _anchor(2)})
    verdicts = [
        _verdict("E1", Action.MASK),
        _verdict("E2", Action.MASK),
        _verdict("E3", Action.MASK),
    ]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"TYPE-phone": KEEP_OPTION}
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.KEEP
    assert by_ref["E1"].decided_by == DecisionSource.TYPE
    assert by_ref["E2"].action is Action.KEEP
    assert by_ref["E3"].action is Action.MASK


def test_profile_keep_answer_affects_only_its_own_entities() -> None:
    person_p1 = _entity(EntityType.PERSON, "Иванов Иван Иванович", 0, 0)
    person_p2 = _entity(EntityType.PERSON, "Петров Пётр Петрович", 1, 0)
    detection = DetectionResult([person_p1, person_p2], [])
    profile_1 = _profile("P1", [person_p1], ["E1"])
    profile_2 = _profile("P2", [person_p2], ["E2"])
    profiles = _profile_result([profile_1, profile_2], {0: _anchor(0), 1: _anchor(1)})
    verdicts = [_verdict("E1", Action.MASK), _verdict("E2", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"PROFILE-P2": KEEP_OPTION}
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK
    assert by_ref["E2"].action is Action.KEEP
    assert by_ref["E2"].question_id == "PROFILE-P2"


def test_personal_answer_overrides_group_type_keep() -> None:
    phone_1 = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    phone_2 = _entity(EntityType.PHONE, "+79007654321", 1, 0)
    detection = DetectionResult([phone_1, phone_2], [])
    profiles = _profile_result([], {0: _anchor(0), 1: _anchor(1)})
    verdicts = [
        _verdict("E1", Action.ASK, question_id="Q1"),
        _verdict("E2", Action.MASK),
    ]
    entity_question = Question(
        id="Q1",
        kind="entity",
        key="phone:+79001234567",
        prompt="Маскировать «+79001234567» как phone?",
        options=(MASK_OPTION, KEEP_OPTION),
        default=MASK_OPTION,
        refs=("E1",),
        anchors=(_anchor(0),),
    )
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        [entity_question],
        questions,
        {"TYPE-phone": KEEP_OPTION, "Q1": MASK_OPTION},
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK
    assert by_ref["E1"].decided_by == DecisionSource.ENTITY
    overridden_sources = {item.decided_by for item in result.overridden["E1"]}
    assert DecisionSource.TYPE in overridden_sources
    assert by_ref["E2"].action is Action.KEEP
    assert by_ref["E2"].decided_by == DecisionSource.TYPE


def test_profile_answer_overrides_type_answer() -> None:
    person_p1 = _entity(EntityType.PERSON, "Иванов Иван Иванович", 0, 0)
    detection = DetectionResult([person_p1], [])
    profile_1 = _profile("P1", [person_p1], ["E1"])
    profiles = _profile_result([profile_1], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        [],
        questions,
        {"TYPE-person": MASK_OPTION, "PROFILE-P1": KEEP_OPTION},
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.KEEP
    assert by_ref["E1"].decided_by == DecisionSource.PROFILE


def test_critical_type_keeps_masking_without_double_confirmation() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    detection = DetectionResult([inn], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"TYPE-inn": KEEP_OPTION}
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK
    assert by_ref["E1"].decided_by == DecisionSource.CRITICAL_GUARD
    assert result.critical_unmasked == []
    assert any("подтвержд" in diagnostic for diagnostic in result.diagnostics)


def test_critical_type_can_be_unmasked_with_double_confirmation() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    detection = DetectionResult([inn], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles, allow_unmask_critical=True)

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        [],
        questions,
        {"TYPE-inn": KEEP_CRITICAL_OPTION},
        allow_unmask_critical=True,
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.KEEP
    assert by_ref["E1"].decided_by == DecisionSource.TYPE
    assert result.critical_unmasked
    assert result.critical_unmasked[0].target == "inn"
    assert result.critical_unmasked[0].count == 1


def test_critical_profile_keep_releases_only_its_non_critical_members() -> None:
    """Обычное «оставить» на профиль снимает маску с некритичной части субъекта,

    а критичные реквизиты того же профиля остаются замаскированными без
    двойного подтверждения — раздел 3 плана T1.5.1.
    """
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    address = _entity(EntityType.ADDRESS, "г. Москва, ул. Ленина, д. 1", 1, 0)
    detection = DetectionResult([inn, address], [])
    profile = _profile("P1", [inn, address], ["E1", "E2"])
    profiles = _profile_result([profile], {0: _anchor(0), 1: _anchor(1)})
    verdicts = [_verdict("E1", Action.MASK), _verdict("E2", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"PROFILE-P1": KEEP_OPTION}
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK  # ИНН — критичный, гвардия держит
    assert by_ref["E1"].decided_by == DecisionSource.CRITICAL_GUARD
    assert by_ref["E2"].action is Action.KEEP  # адрес — некритичный, отпущен
    assert by_ref["E2"].decided_by == DecisionSource.PROFILE


def test_critical_profile_releases_critical_members_with_double_confirmation() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    address = _entity(EntityType.ADDRESS, "г. Москва, ул. Ленина, д. 1", 1, 0)
    detection = DetectionResult([inn, address], [])
    profile = _profile("P1", [inn, address], ["E1", "E2"])
    profiles = _profile_result([profile], {0: _anchor(0), 1: _anchor(1)})
    verdicts = [_verdict("E1", Action.MASK), _verdict("E2", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles, allow_unmask_critical=True)

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        [],
        questions,
        {"PROFILE-P1": KEEP_CRITICAL_OPTION},
        allow_unmask_critical=True,
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.KEEP
    assert by_ref["E1"].decided_by == DecisionSource.PROFILE
    assert by_ref["E2"].action is Action.KEEP
    assert result.critical_unmasked
    assert result.critical_unmasked[0].question_id == "PROFILE-P1"
    assert result.critical_unmasked[0].target == "inn"


def test_critical_profile_plain_keep_does_not_confirm_critical_members_even_with_flag() -> None:
    """Флаг сам по себе не подтверждение: нужен именно KEEP_CRITICAL_OPTION."""
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    detection = DetectionResult([inn], [])
    profile = _profile("P1", [inn], ["E1"])
    profiles = _profile_result([profile], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles, allow_unmask_critical=True)

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        [],
        questions,
        {"PROFILE-P1": KEEP_OPTION},
        allow_unmask_critical=True,
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK
    assert by_ref["E1"].decided_by == DecisionSource.CRITICAL_GUARD
    assert result.critical_unmasked == []


def test_missing_answer_uses_default_and_is_reported() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(detection, profiles, verdicts, [], questions, {})

    assert "TYPE-phone" in result.unanswered_defaults
    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK


def test_unknown_question_id_is_ignored_not_fatal() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"TYPE-phone": KEEP_OPTION, "H1": "оставить"}
    )

    assert "H1" in result.ignored_answers


def test_invalid_option_value_falls_back_to_default() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {"TYPE-phone": "нечто странное"}
    )

    assert "TYPE-phone" in result.invalid_answers
    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.MASK


def test_result_order_is_independent_of_answers_dict_key_order() -> None:
    phone_1 = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    phone_2 = _entity(EntityType.PHONE, "+79007654321", 1, 0)
    person = _entity(EntityType.PERSON, "Иванов Иван Иванович", 2, 0)
    detection = DetectionResult([phone_1, phone_2, person], [])
    profiles = _profile_result([], {0: _anchor(0), 1: _anchor(1), 2: _anchor(2)})
    verdicts = [
        _verdict("E1", Action.MASK),
        _verdict("E2", Action.MASK),
        _verdict("E3", Action.MASK),
    ]
    questions = PolicyAgent().questions(detection, profiles)
    answers = {"TYPE-phone": KEEP_OPTION, "TYPE-person": MASK_OPTION}
    shuffled_items = list(answers.items())
    random.Random(42).shuffle(shuffled_items)

    first = PolicyAgent().apply(detection, profiles, verdicts, [], questions, answers)
    second = PolicyAgent().apply(detection, profiles, verdicts, [], questions, dict(shuffled_items))

    assert first.decisions == second.decisions


def test_foreign_ref_namespace_in_answers_does_not_crash_and_is_ignored() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = _profile_result([], {0: _anchor(0)})
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(detection, profiles, verdicts, [], questions, {"H1": MASK_OPTION})

    assert "H1" in result.ignored_answers
    assert len(result.decisions) == 1


def test_entities_without_profile_use_profile_unassigned_question() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = _profile_result([], {0: _anchor(0)})
    profiles.unassigned = ["E1"]
    verdicts = [_verdict("E1", Action.MASK)]
    questions = PolicyAgent().questions(detection, profiles)

    result = PolicyAgent().apply(
        detection, profiles, verdicts, [], questions, {PROFILE_UNASSIGNED: KEEP_OPTION}
    )

    by_ref = {decision.ref: decision for decision in result.decisions}
    assert by_ref["E1"].action is Action.KEEP
    assert by_ref["E1"].decided_by == DecisionSource.PROFILE
