"""Узлы графа: extract → detect → profile → judge → policy → ask_human/apply.

LLM в ``State`` не кладётся: узлы, которым он нужен, собираются фабриками
(``make_profile_node``, ``make_judge_node``), замыкающими ``RunDeps``. Это
даёт один и тот же провод CLI и веб-серверу — меняется только вызывающий и
чекпойнтер, а не логика узлов (требование заказчика №6, ``AGENTS.md``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from langgraph.types import interrupt

from masker.detect import AddressDetector, DetectAgent, RuleDetector
from masker.detect.result import DetectionResult, build_pii_chunks
from masker.graph.questions import build_ask_payload
from masker.graph.serde import (
    anchor_from_dict,
    decisions_to_dicts,
    entity_from_dict,
    entity_to_dict,
    policy_questions_from_dicts,
    policy_questions_to_dicts,
    profiles_from_dicts,
    profiles_to_dicts,
    questions_from_dicts,
    questions_to_dicts,
    verdicts_from_dicts,
    verdicts_to_dicts,
)
from masker.graph.state import State
from masker.ingest.docx_ingest import ingest_docx
from masker.judge import JudgeAgent
from masker.judge.agent import JudgeResult
from masker.llm import LLMProvider, TracingProvider
from masker.model import Document, EntityType, Segment
from masker.policy.agent import CriticalUnmask, GroupAnswer, PolicyAgent
from masker.profile import ProfileAgent
from masker.profile.agent import ProfileResult


@dataclass(frozen=True, slots=True)
class RunDeps:
    """Внешние зависимости узлов графа: провайдер LLM и трейсер обмена с ним.

    Не входит в ``State`` (только JSON) — узлы замыкают эти зависимости через
    фабрики (``make_profile_node`` и т.д.), поэтому вызывающий (CLI сегодня,
    веб завтра) сам решает, каким провайдером и чекпойнтером пользоваться.
    """

    llm: LLMProvider | None = None
    tracer: TracingProvider | None = None


def _document(state: State) -> Document:
    return Document(
        path=state.get("path", ""),
        fmt=state.get("fmt", "docx"),
        segments=[
            Segment(str(item["text"]), anchor_from_dict(item["anchor"]), int(item["order"]))
            for item in state["segments"]
        ],
    )


def extract_node(state: State) -> dict[str, object]:
    """Разобрать DOCX по ``state["path"]`` в сегменты, формат и метаданные."""
    path = Path(state["path"])
    document = ingest_docx(path)
    return {
        "fmt": document.fmt,
        "segments": [
            {
                "text": segment.text,
                "anchor": {
                    "fmt": segment.anchor.fmt,
                    "locator": list(segment.anchor.locator),
                    "label": segment.anchor.label,
                },
                "order": segment.order,
            }
            for segment in document.segments
        ],
        "meta": {**document.meta, "name": path.name},
    }


def detect_node(state: State) -> dict[str, object]:
    """Трёхслойная детекция, отфильтрованная по ``options.types`` и ``rules_only``."""
    document = _document(state)
    options = state.get("options", {})
    rules_only = bool(options.get("rules_only", False))
    detector = DetectAgent([RuleDetector(), AddressDetector()]) if rules_only else DetectAgent()
    raw_types = options.get("types")
    selected_types = (
        {EntityType(str(value)) for value in raw_types} if raw_types else set(EntityType)
    )
    entities = [
        entity for entity in detector.detect(document).entities if entity.type in selected_types
    ]
    return {"entities": [entity_to_dict(entity) for entity in entities]}


def make_profile_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``profile_node``, использующий LLM из ``deps`` (не теряется)."""

    def profile_node(state: State) -> dict[str, object]:
        document = _document(state)
        entities = [entity_from_dict(item) for item in state["entities"]]
        result = ProfileAgent(deps.llm).profile(
            document, DetectionResult(entities, build_pii_chunks(document.segments, entities))
        )
        return {
            "profiles": profiles_to_dicts(result.profiles),
            "unassigned": result.unassigned,
            "candidates": [entity_to_dict(item) for item in result.candidates],
            "diagnostics": result.diagnostics,
        }

    return profile_node


def _profile_result(state: State, document: Document) -> ProfileResult:
    return ProfileResult(
        profiles=profiles_from_dicts(state.get("profiles", [])),
        blocks=[],
        unassigned=list(state.get("unassigned", [])),
        candidates=[entity_from_dict(item) for item in state.get("candidates", [])],
        anchors={segment.order: segment.anchor for segment in document.segments},
        diagnostics=list(state.get("diagnostics", [])),
    )


def make_judge_node(deps: RunDeps) -> Callable[[State], dict[str, object]]:
    """Собрать ``judge_node``. ``JudgeAgent`` сегодня LLM не использует,

    но узел — фабрика наравне с ``profile_node``: судья исторически не
    зависел от модели, но провод остаётся однородным для обоих узлов.
    """

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

    return judge_node


def policy_node(state: State) -> dict[str, object]:
    """Построить вопросы политики по фактически найденным типам и профилям."""
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = _profile_result(state, document)
    allow_unmask_critical = bool(state.get("options", {}).get("unmask_critical", False))
    questions = PolicyAgent().questions(
        detection, profiles, allow_unmask_critical=allow_unmask_critical
    )
    return {"policy_questions": policy_questions_to_dicts(questions)}


def ask_human_node(state: State) -> dict[str, object]:
    """Ровно один LangGraph interrupt на единый конверт вопросов (раздел 5).

    Без побочных эффектов: LangGraph выполняет этот узел заново при каждом
    возобновлении приостановленного треда (проверено пробоем — раздел 2 плана
    T1.5.1), поэтому узел не пишет файлы и не меняет входной ``state``.
    """
    return {"answers": interrupt(build_ask_payload(state))}


def apply_answers_node(state: State) -> dict[str, object]:
    """Применить ответы человека к вопросам судьи, обновив вердикты."""
    result = JudgeResult(
        verdicts_from_dicts(state.get("verdicts", [])),
        questions_from_dicts(state.get("questions", [])),
    )
    return {
        "verdicts": verdicts_to_dicts(JudgeAgent().apply_answers(result, state.get("answers", {})))
    }


def _group_answer_to_dict(item: GroupAnswer) -> dict[str, object]:
    return {
        "id": item.id,
        "kind": item.kind,
        "target": item.target,
        "answer": item.answer,
        "source": item.source,
    }


def _critical_unmask_to_dict(item: CriticalUnmask) -> dict[str, object]:
    return {
        "question_id": item.question_id,
        "kind": item.kind,
        "target": item.target,
        "count": item.count,
    }


def finalize_node(state: State) -> dict[str, object]:
    """Свести решения судьи и политики в одно действие на каждый ``ref``.

    Алгоритм разрешения конфликтов — ``PolicyAgent.apply`` (раздел 7 плана
    T1.5.1). Запись артефактов остаётся снаружи графа — узлы не пишут файлы.
    """
    document = _document(state)
    entities = [entity_from_dict(item) for item in state["entities"]]
    detection = DetectionResult(entities, build_pii_chunks(document.segments, entities))
    profiles = _profile_result(state, document)
    verdicts = verdicts_from_dicts(state.get("verdicts", []))
    judge_questions = questions_from_dicts(state.get("questions", []))
    policy_questions = policy_questions_from_dicts(state.get("policy_questions", []))
    answers = state.get("answers", {})
    options = state.get("options", {})
    allow_unmask_critical = bool(options.get("unmask_critical", False))

    result = PolicyAgent().apply(
        detection,
        profiles,
        verdicts,
        judge_questions,
        policy_questions,
        answers,
        allow_unmask_critical=allow_unmask_critical,
    )

    return {
        "final_actions": decisions_to_dicts(result.decisions, result.overridden),
        "decisions": {
            "mode": "interactive" if options.get("interactive") else "non_interactive",
            "types": [_group_answer_to_dict(item) for item in result.types],
            "profiles": [_group_answer_to_dict(item) for item in result.profiles],
            "critical_unmasked": [
                _critical_unmask_to_dict(item) for item in result.critical_unmasked
            ],
            "unanswered_defaults": result.unanswered_defaults,
            "ignored_answers": result.ignored_answers,
            "invalid_answers": result.invalid_answers,
            "diagnostics": result.diagnostics,
        },
    }


def needs_human(state: State) -> str:
    """Направить на ``ask_human`` только если это действительно нужно.

    Единственная защита ворот от зависания (раздел 6 плана T1.5.1):
    неинтерактивный прогон (``options.interactive`` ложно) и прогон, для
    которого ответы уже заданы заранее, идут сразу на ``apply_answers``.
    """
    options = state.get("options", {})
    interactive = bool(options.get("interactive", False))
    has_questions = bool(state.get("policy_questions")) or bool(state.get("questions"))
    already_answered = bool(state.get("answers"))
    if interactive and has_questions and not already_answered:
        return "ask_human"
    return "apply_answers"
