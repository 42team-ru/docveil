"""Сборка ``StateGraph`` и подключение чекпойнтера (раздел 6 плана T1.5.1).

Чекпойнтер передаётся снаружи (``compile_graph(deps, checkpointer)``), а не
создаётся внутри узлов: логика узлов не меняется при переезде CLI на
веб-сервер — меняется только вызывающий и чекпойнтер (``SqliteSaver`` →
серверный). ``SqliteSaver`` однопоточный и не годится под конкурентный
веб-сервер — серверу нужен свой saver, см. ``run.py``.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from masker.graph.nodes import (
    RunDeps,
    apply_answers_node,
    apply_review_edits_node,
    ask_human_node,
    ask_review_node,
    finalize_node,
    image_export_node,
    make_detect_node,
    make_extract_node,
    make_judge_node,
    make_profile_node,
    make_render_node,
    make_report_node,
    make_summary_node,
    needs_human,
    needs_review,
    plan_node,
    policy_node,
    validate_node,
)
from masker.graph.state import State
from masker.telemetry import append_stage

__all__ = ["RunDeps", "build_graph", "compile_graph"]


def _instrument(
    name: str, node: Callable[[State], dict[str, object]], deps: RunDeps
) -> Callable[[State], dict[str, object]]:
    """Добавить к каждому узлу дешёвый замер и ленту без значений PII."""

    def wrapped(state: State) -> dict[str, object]:
        deps.notify_stage(name, "started")
        offset = deps.metering_offset()
        started = time.perf_counter()
        result = node(state)
        duration_ms = (time.perf_counter() - started) * 1000
        combined = {**state, **result}
        message = _event_message(name, combined)
        deps.notify_stage(name, "completed", message)
        return {
            **result,
            "telemetry": append_stage(
                state.get("telemetry"),
                node=name,
                duration_ms=duration_ms,
                message=message,
                calls=deps.metering_delta(offset),
                pricing=deps.pricing,
            ),
        }

    return wrapped


def _event_message(node: str, state: dict[str, object]) -> str:
    """Сформулировать понятное событие только из счётчиков, не из текста документа."""
    if node == "extract":
        fmt = str(state.get("fmt", "документ")).upper()
        coverage = state.get("coverage", {})
        if isinstance(coverage, dict) and isinstance(coverage.get("pages"), dict):
            return f"разобран {fmt}, {int(coverage['pages'].get('count', 0))} страниц"
        return f"разобран {fmt}, сегментов текста: {len(state.get('segments', []))}"  # type: ignore[arg-type]
    if node == "detect":
        # `State` — нетипизированный словарь графа: сужаем явно, иначе mypy
        # видит `object`, а на неверном содержимом узел молча падал бы.
        raw = state.get("entities", [])
        entities = raw if isinstance(raw, list) else []
        sources = Counter(
            str(item.get("source", "unknown")) for item in entities if isinstance(item, dict)
        )
        details = ", ".join(f"{source} {count}" for source, count in sorted(sources.items()))
        return f"найдено сущностей {len(entities)}" + (f": {details}" if details else "")
    if node == "profile":
        return f"определено профилей сторон: {len(state.get('profiles', []))}"  # type: ignore[arg-type]
    if node in {"judge", "policy", "ask_human"}:
        questions = len(state.get("questions", [])) + len(state.get("policy_questions", []))  # type: ignore[arg-type]
        return f"вопросов пользователю: {questions}"
    if node in {"plan", "apply_review_edits"}:
        plan = state.get("plan", {})
        replacements = plan.get("replacements", []) if isinstance(plan, dict) else []
        return f"сформировано замен {len(replacements)}"
    if node == "render":
        return f"сформировано файлов: {len(state.get('artifacts', []))}"  # type: ignore[arg-type]
    if node == "validate":
        return f"проверены артефакты, утечек: {len(state.get('leaked', []))}"  # type: ignore[arg-type]
    if node == "report":
        return "сформирован отчёт"
    return f"выполнен узел {node}"


def build_graph(deps: RunDeps) -> StateGraph[State]:
    """Собрать граф раздела 6 плана T1.5.1, дополненный ``plan``/``render``/
    ``validate``/``report`` (T1.10, шаги 4—7):

    ``extract → detect → profile → judge → policy →`` (``ask_human`` при
    необходимости) `` → apply_answers → finalize → plan → render → validate
    → report → END``.
    """
    graph: StateGraph[State] = StateGraph(State)
    graph.add_node("extract", _instrument("extract", make_extract_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("detect", _instrument("detect", make_detect_node(deps), deps))  # type: ignore[call-overload]
    # mypy не умеет вывести NodeInputT из значения типа Callable[[State], ...],
    # только из def-функции с конкретной сигнатурой (проверено минимальным
    # воспроизведением на langgraph 1.2.11): без игнора аргумент разрешается
    # в _Node[Never]. Реальная сигнатура узла типизирована в nodes.py.
    graph.add_node("profile", _instrument("profile", make_profile_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("judge", _instrument("judge", make_judge_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("policy", _instrument("policy", policy_node, deps))  # type: ignore[call-overload]
    graph.add_node("ask_human", _instrument("ask_human", ask_human_node, deps))  # type: ignore[call-overload]
    graph.add_node("apply_answers", _instrument("apply_answers", apply_answers_node, deps))  # type: ignore[call-overload]
    graph.add_node("finalize", _instrument("finalize", finalize_node, deps))  # type: ignore[call-overload]
    graph.add_node("plan", _instrument("plan", plan_node, deps))  # type: ignore[call-overload]
    graph.add_node("summary", _instrument("summary", make_summary_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("render", _instrument("render", make_render_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("validate", _instrument("validate", validate_node, deps))  # type: ignore[call-overload]
    graph.add_node("image_export", _instrument("image_export", image_export_node, deps))  # type: ignore[call-overload]
    graph.add_node("report", _instrument("report", make_report_node(deps), deps))  # type: ignore[call-overload]
    graph.add_node("ask_review", _instrument("ask_review", ask_review_node, deps))  # type: ignore[call-overload]
    graph.add_node(  # type: ignore[call-overload]
        "apply_review_edits",
        _instrument("apply_review_edits", apply_review_edits_node, deps),
    )

    graph.add_edge(START, "extract")
    graph.add_edge("extract", "detect")
    graph.add_edge("detect", "profile")
    graph.add_edge("profile", "judge")
    graph.add_edge("judge", "policy")
    graph.add_conditional_edges(
        "policy",
        needs_human,
        {"ask_human": "ask_human", "apply_answers": "apply_answers"},
    )
    graph.add_edge("ask_human", "apply_answers")
    graph.add_edge("apply_answers", "finalize")
    graph.add_edge("finalize", "plan")
    graph.add_edge("plan", "summary")
    graph.add_edge("summary", "render")
    graph.add_edge("render", "validate")
    # `image_export` идёт после валидации: проверка PDF-артефакта «нет
    # исходной строки» выполняется до подмены на JPEG/PNG/TIFF.
    graph.add_edge("validate", "image_export")
    graph.add_edge("image_export", "report")
    # Второй круг: оператор видит отчёт и правит результат, после чего
    # документ пересобирается тем же путём plan → … → report. Ровно один
    # раунд — иначе прогон не заканчивается никогда (``needs_review``).
    graph.add_conditional_edges(
        "report",
        needs_review,
        {"ask_review": "ask_review", "end": END},
    )
    graph.add_edge("ask_review", "apply_review_edits")
    graph.add_edge("apply_review_edits", "plan")
    return graph


def compile_graph(
    deps: RunDeps, checkpointer: BaseCheckpointSaver[str]
) -> CompiledStateGraph[State, None, State, State]:
    """Скомпилировать граф с внешним чекпойнтером — основа durable resume."""
    return build_graph(deps).compile(checkpointer=checkpointer)
