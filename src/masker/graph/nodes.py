"""Узлы profile/judge с одним прерыванием на весь набор вопросов."""

from __future__ import annotations

from langgraph.types import interrupt

from masker.detect.result import DetectionResult, build_pii_chunks
from masker.graph.serde import (
    anchor_from_dict,
    entity_from_dict,
    entity_to_dict,
    profiles_from_dicts,
    profiles_to_dicts,
    questions_from_dicts,
    questions_to_dicts,
    verdicts_from_dicts,
    verdicts_to_dicts,
)
from masker.graph.state import State
from masker.judge import JudgeAgent
from masker.judge.agent import JudgeResult
from masker.model import Document, Segment
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult


def _document(state: State) -> Document:
    return Document(
        path=state.get("path", ""),
        fmt=state.get("fmt", "docx"),
        segments=[
            Segment(str(item["text"]), anchor_from_dict(item["anchor"]), int(item["order"]))
            for item in state["segments"]
        ],
    )


def profile_node(state: State) -> dict[str, object]:
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    result = ProfileAgent().profile(
        document, DetectionResult(entities, build_pii_chunks(document.segments, entities))
    )
    return {
        "profiles": profiles_to_dicts(result.profiles),
        "unassigned": result.unassigned,
        "candidates": [entity_to_dict(item) for item in result.candidates],
        "diagnostics": result.diagnostics,
    }


def _profile_result(state: State, document: Document) -> ProfileResult:
    return ProfileResult(
        profiles=profiles_from_dicts(state.get("profiles", [])),
        blocks=[],
        unassigned=list(state.get("unassigned", [])),
        candidates=[entity_from_dict(item) for item in state.get("candidates", [])],
        anchors={segment.order: segment.anchor for segment in document.segments},
        diagnostics=list(state.get("diagnostics", [])),
    )


def judge_node(state: State) -> dict[str, object]:
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    result = JudgeAgent().judge(
        DetectionResult(entities, build_pii_chunks(document.segments, entities)),
        _profile_result(state, document),
    )
    return {
        "verdicts": verdicts_to_dicts(result.verdicts),
        "questions": questions_to_dicts(result.questions),
    }


def ask_human_node(state: State) -> dict[str, object]:
    """Ровно одно LangGraph interrupt на целую пачку вопросов."""
    return {"answers": interrupt({"questions": state.get("questions", [])})}


def apply_answers_node(state: State) -> dict[str, object]:
    result = JudgeResult(
        verdicts_from_dicts(state.get("verdicts", [])),
        questions_from_dicts(state.get("questions", [])),
    )
    return {
        "verdicts": verdicts_to_dicts(JudgeAgent().apply_answers(result, state.get("answers", {})))
    }


def needs_human(state: State) -> str:
    return "ask_human" if state.get("questions") else "plan"
