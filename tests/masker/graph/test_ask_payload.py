"""Единый конверт вопросов и разбор ответов человека — раздел 5 плана T1.5.1."""

from __future__ import annotations

import json

import pytest

from masker.graph.questions import SCHEMA_VERSION, build_ask_payload, parse_answers
from masker.graph.serde import policy_questions_to_dicts, questions_to_dicts
from masker.graph.state import State
from masker.model import Anchor, PolicyQuestion, Question

REQUIRED_KEYS = {
    "id",
    "kind",
    "target",
    "title",
    "prompt",
    "options",
    "default",
    "critical",
    "found",
    "samples",
    "anchors",
}


def _state() -> State:
    type_question = PolicyQuestion(
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
        anchors=(Anchor(fmt="docx", locator=("body", 5), label="абзац 6"),),
        linked=(),
        role_title="",
    )
    profile_question = PolicyQuestion(
        id="PROFILE-P3",
        kind="profile",
        target="P3",
        title="СТОРОНА-3",
        prompt="Маскировать реквизиты субъекта СТОРОНА-3 (найдено сущностей: 4)?",
        options=("маскировать", "оставить"),
        default="маскировать",
        critical=False,
        found=4,
        by_type=(("inn", 1), ("address", 2), ("person", 1)),
        samples=("3662103003", "309512, Белгородская область"),
        anchors=(Anchor(fmt="docx", locator=("table", 0, 0, 0, 5), label="таблица 1, абзац 6"),),
        linked=("P4", "P5"),
        role_title="",
    )
    entity_question = Question(
        id="Q1",
        kind="entity",
        key="phone:+79001234567",
        prompt="Маскировать «+7 900 123-45-67» как phone?",
        options=("маскировать", "оставить"),
        default="маскировать",
        refs=("E7",),
        anchors=(Anchor(fmt="docx", locator=("body", 6), label="абзац 7"),),
    )
    return {
        "meta": {"name": "contract_01.docx", "format": "docx"},
        "options": {"thread_id": "0f3a1234567890ab"},
        "policy_questions": policy_questions_to_dicts([type_question, profile_question]),
        "questions": questions_to_dicts([entity_question]),
    }


def test_envelope_has_required_keys_for_every_question() -> None:
    payload = build_ask_payload(_state())

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["thread_id"] == "0f3a1234567890ab"
    assert payload["document"] == {"name": "contract_01.docx", "format": "docx"}
    for question in payload["questions"]:
        assert question.keys() >= REQUIRED_KEYS


def test_question_ids_are_unique() -> None:
    payload = build_ask_payload(_state())
    ids = [question["id"] for question in payload["questions"]]
    assert len(ids) == len(set(ids))


def test_order_is_types_then_profiles_then_entities() -> None:
    payload = build_ask_payload(_state())
    kinds = [question["kind"] for question in payload["questions"]]
    assert kinds == ["type", "profile", "entity"]


def test_envelope_json_dumps_is_deterministic() -> None:
    payload = build_ask_payload(_state())
    first = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    second = json.dumps(build_ask_payload(_state()), ensure_ascii=False, sort_keys=True)
    assert first == second


def test_entity_question_anchors_and_samples_are_plain_strings() -> None:
    payload = build_ask_payload(_state())
    entity_question = next(q for q in payload["questions"] if q["kind"] == "entity")
    assert entity_question["anchors"] == ["абзац 7"]
    assert entity_question["samples"] == ["+79001234567"]
    assert entity_question["critical"] is False
    assert entity_question["found"] == 1


def test_unknown_kind_does_not_break_the_payload() -> None:
    """Страховка под будущий вид вопроса ``kind: "pii"`` — раздел 4 плана T1.5.1."""
    future_question = PolicyQuestion(
        id="PII-H1",
        kind="pii",
        target="H1",
        title="Отмеченный вручную фрагмент",
        prompt="Маскировать выделенный фрагмент?",
        options=("маскировать", "оставить"),
        default="маскировать",
        critical=False,
        found=1,
        by_type=(),
        samples=("образец",),
        anchors=(),
        linked=(),
        role_title="",
    )
    state = _state()
    state["policy_questions"] = [
        *state["policy_questions"],
        *policy_questions_to_dicts([future_question]),
    ]

    payload = build_ask_payload(state)

    pii_question = next(q for q in payload["questions"] if q["id"] == "PII-H1")
    assert pii_question.keys() >= REQUIRED_KEYS


def test_parse_answers_rejects_foreign_schema_version() -> None:
    with pytest.raises(ValueError, match="версия схемы"):
        parse_answers({"schema_version": 999, "answers": {"TYPE-inn": "маскировать"}})


def test_parse_answers_drops_non_string_values() -> None:
    answers = parse_answers(
        {
            "schema_version": SCHEMA_VERSION,
            "answers": {"TYPE-inn": "маскировать", "TYPE-phone": 1, "PROFILE-P3": None},
        }
    )
    assert answers == {"TYPE-inn": "маскировать"}
