"""PolicyAgent.questions(): вопросы по типам и профилям на синтетических данных."""

from __future__ import annotations

from masker.detect.result import DetectionResult
from masker.model import (
    KEEP_CRITICAL_OPTION,
    KEEP_OPTION,
    MASK_OPTION,
    Anchor,
    Entity,
    EntityType,
    Profile,
    ProfileMember,
    Source,
)
from masker.policy.agent import PROFILE_UNASSIGNED, PolicyAgent
from masker.profile.agent import ProfileResult


def _entity(
    entity_type: EntityType,
    text: str,
    segment_order: int = 0,
    start: int = 0,
    normalized: str = "",
) -> Entity:
    return Entity(
        type=entity_type,
        text=text,
        segment_order=segment_order,
        start=start,
        end=start + len(text),
        source=Source.RULE,
        confidence=1.0,
        normalized=normalized,
    )


def _anchor(segment_order: int, label: str) -> Anchor:
    return Anchor(fmt="docx", locator=("body", segment_order), label=label)


def test_type_questions_are_ordered_alphabetically_by_type_value() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    person = _entity(EntityType.PERSON, "Иванов Иван Иванович", 1, 0)
    phone = _entity(EntityType.PHONE, "+79001234567", 2, 0)
    detection = DetectionResult([inn, person, phone], [])
    anchors = {0: _anchor(0, "абзац 1"), 1: _anchor(1, "абзац 2"), 2: _anchor(2, "абзац 3")}
    profiles = ProfileResult(profiles=[], blocks=[], unassigned=["E1", "E2", "E3"], candidates=[])
    profiles.anchors = anchors

    questions = PolicyAgent().questions(detection, profiles)

    type_ids = [q.id for q in questions if q.kind == "type"]
    assert type_ids == ["TYPE-inn", "TYPE-person", "TYPE-phone"]


def test_critical_type_question_offers_only_mask_by_default() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    detection = DetectionResult([inn], [])
    profiles = ProfileResult(profiles=[], blocks=[], unassigned=["E1"], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1")}

    questions = PolicyAgent().questions(detection, profiles)
    inn_question = next(q for q in questions if q.id == "TYPE-inn")

    assert inn_question.options == (MASK_OPTION,)
    assert inn_question.critical is True


def test_critical_type_question_offers_conscious_keep_with_flag() -> None:
    inn = _entity(EntityType.INN, "3662103003", 0, 0)
    detection = DetectionResult([inn], [])
    profiles = ProfileResult(profiles=[], blocks=[], unassigned=["E1"], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1")}

    questions = PolicyAgent().questions(detection, profiles, allow_unmask_critical=True)
    inn_question = next(q for q in questions if q.id == "TYPE-inn")

    assert inn_question.options == (MASK_OPTION, KEEP_CRITICAL_OPTION)


def test_non_critical_type_offers_mask_and_keep() -> None:
    phone = _entity(EntityType.PHONE, "+79001234567", 0, 0)
    detection = DetectionResult([phone], [])
    profiles = ProfileResult(profiles=[], blocks=[], unassigned=["E1"], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1")}

    questions = PolicyAgent().questions(detection, profiles)
    phone_question = next(q for q in questions if q.id == "TYPE-phone")

    assert phone_question.options == (MASK_OPTION, KEEP_OPTION)


def _profile_without_role(profile_id: str, entities: list[Entity]) -> Profile:
    return Profile(
        id=profile_id,
        members=[
            ProfileMember(
                entity, _anchor(entity.segment_order, f"абзац {entity.segment_order + 1}"), f"E{i}"
            )
            for i, entity in enumerate(entities, 1)
        ],
        role_id="",
        role_title="",
        marker_label=f"СТОРОНА-{profile_id[1:]}",
        confidence=1.0,
        source=Source.RULE,
    )


def test_profile_without_role_shows_marker_label_and_no_role_word() -> None:
    entities = [
        _entity(EntityType.INN, "3662103003", 0, 0),
        _entity(EntityType.ADDRESS, "г. Москва, ул. Ленина, д. 1", 0, 20),
    ]
    profile = _profile_without_role("P3", entities)
    detection = DetectionResult(entities, [])
    profiles = ProfileResult(profiles=[profile], blocks=[], unassigned=[], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1")}

    questions = PolicyAgent().questions(detection, profiles)
    profile_question = next(q for q in questions if q.id == "PROFILE-P3")

    assert profile_question.title == "СТОРОНА-3"
    assert profile_question.samples
    assert profile_question.anchors
    assert "роль" not in profile_question.prompt.casefold()


def test_profile_with_critical_entity_is_marked_critical_without_conscious_option() -> None:
    entities = [_entity(EntityType.INN, "3662103003", 0, 0)]
    profile = _profile_without_role("P1", entities)
    detection = DetectionResult(entities, [])
    profiles = ProfileResult(profiles=[profile], blocks=[], unassigned=[], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1")}

    questions = PolicyAgent().questions(detection, profiles)
    profile_question = next(q for q in questions if q.id == "PROFILE-P1")

    # У профиля критичность не «всё или ничего»: обычное «оставить» доступно
    # всегда (снимает маску с некритичной части субъекта), а осознанный
    # вариант для критичных реквизитов — только с --unmask-critical.
    assert profile_question.critical is True
    assert KEEP_CRITICAL_OPTION not in profile_question.options
    assert profile_question.options == (MASK_OPTION, KEEP_OPTION)


def test_profiles_with_same_normalized_inn_link_to_each_other_but_stay_two_questions() -> None:
    entity_1 = _entity(EntityType.INN, "3662103003", 0, 0)
    entity_2 = _entity(EntityType.INN, "3662103003", 1, 0)
    profile_1 = _profile_without_role("P1", [entity_1])
    profile_2 = _profile_without_role("P2", [entity_2])
    detection = DetectionResult([entity_1, entity_2], [])
    profiles = ProfileResult(
        profiles=[profile_1, profile_2], blocks=[], unassigned=[], candidates=[]
    )
    profiles.anchors = {0: _anchor(0, "абзац 1"), 1: _anchor(1, "абзац 2")}

    questions = PolicyAgent().questions(detection, profiles)
    profile_questions = [q for q in questions if q.kind == "profile"]

    assert len(profile_questions) == 2
    q1 = next(q for q in profile_questions if q.id == "PROFILE-P1")
    q2 = next(q for q in profile_questions if q.id == "PROFILE-P2")
    assert q1.linked == ("P2",)
    assert q2.linked == ("P1",)


def test_entities_outside_profiles_produce_exactly_one_unassigned_question() -> None:
    assigned_entity = _entity(EntityType.INN, "3662103003", 0, 0)
    unassigned_entity = _entity(EntityType.PHONE, "+79001234567", 1, 0)
    profile = _profile_without_role("P1", [assigned_entity])
    detection = DetectionResult([assigned_entity, unassigned_entity], [])
    profiles = ProfileResult(profiles=[profile], blocks=[], unassigned=["E2"], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1"), 1: _anchor(1, "абзац 2")}

    questions = PolicyAgent().questions(detection, profiles)
    profile_questions = [q for q in questions if q.kind == "profile"]

    assert [q.id for q in profile_questions] == ["PROFILE-P1", PROFILE_UNASSIGNED]
    unassigned_question = next(q for q in profile_questions if q.id == PROFILE_UNASSIGNED)
    assert unassigned_question.found == 1


def test_questions_are_deterministic_across_calls() -> None:
    entities = [
        _entity(EntityType.INN, "3662103003", 0, 0),
        _entity(EntityType.PHONE, "+79001234567", 1, 0),
    ]
    profile = _profile_without_role("P1", [entities[0]])
    detection = DetectionResult(entities, [])
    profiles = ProfileResult(profiles=[profile], blocks=[], unassigned=["E2"], candidates=[])
    profiles.anchors = {0: _anchor(0, "абзац 1"), 1: _anchor(1, "абзац 2")}

    first = PolicyAgent().questions(detection, profiles)
    second = PolicyAgent().questions(detection, profiles)

    assert first == second
