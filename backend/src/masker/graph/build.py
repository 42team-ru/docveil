"""Сборка ``StateGraph`` и подключение чекпойнтера (раздел 6 плана T1.5.1).

Чекпойнтер передаётся снаружи (``compile_graph(deps, checkpointer)``), а не
создаётся внутри узлов: логика узлов не меняется при переезде CLI на
веб-сервер — меняется только вызывающий и чекпойнтер (``SqliteSaver`` →
серверный). ``SqliteSaver`` однопоточный и не годится под конкурентный
веб-сервер — серверу нужен свой saver, см. ``run.py``.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from masker.graph.nodes import (
    RunDeps,
    apply_answers_node,
    ask_human_node,
    finalize_node,
    image_export_node,
    make_detect_node,
    make_extract_node,
    make_judge_node,
    make_profile_node,
    make_render_node,
    make_report_node,
    needs_human,
    plan_node,
    policy_node,
    summary_node,
    validate_node,
)
from masker.graph.state import State

__all__ = ["RunDeps", "build_graph", "compile_graph"]


def build_graph(deps: RunDeps) -> StateGraph[State]:
    """Собрать граф раздела 6 плана T1.5.1, дополненный ``plan``/``render``/
    ``validate``/``report`` (T1.10, шаги 4—7):

    ``extract → detect → profile → judge → policy →`` (``ask_human`` при
    необходимости) `` → apply_answers → finalize → plan → render → validate
    → report → END``.
    """
    graph: StateGraph[State] = StateGraph(State)
    graph.add_node("extract", make_extract_node(deps))
    graph.add_node("detect", make_detect_node(deps))
    # mypy не умеет вывести NodeInputT из значения типа Callable[[State], ...],
    # только из def-функции с конкретной сигнатурой (проверено минимальным
    # воспроизведением на langgraph 1.2.11): без игнора аргумент разрешается
    # в _Node[Never]. Реальная сигнатура узла типизирована в nodes.py.
    graph.add_node("profile", make_profile_node(deps))
    graph.add_node("judge", make_judge_node(deps))
    graph.add_node("policy", policy_node)
    graph.add_node("ask_human", ask_human_node)
    graph.add_node("apply_answers", apply_answers_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("plan", plan_node)
    graph.add_node("summary", summary_node)
    graph.add_node("render", make_render_node(deps))
    graph.add_node("validate", validate_node)
    graph.add_node("image_export", image_export_node)
    graph.add_node("report", make_report_node(deps))

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
    # `image_export` идёт **после** валидации: побайтовая проверка «нет
    # исходной строки» выполняется на PDF-артефакте (инвариант 2 плана
    # feat-image-ingest.md — JPEG после пересжатия побайтово другой), а
    # уже потом PDF-артефакты подменяются картинками нужного формата.
    graph.add_edge("validate", "image_export")
    graph.add_edge("image_export", "report")
    graph.add_edge("report", END)
    return graph


def compile_graph(
    deps: RunDeps, checkpointer: BaseCheckpointSaver[str]
) -> CompiledStateGraph[State, None, State, State]:
    """Скомпилировать граф с внешним чекпойнтером — основа durable resume."""
    return build_graph(deps).compile(checkpointer=checkpointer)
