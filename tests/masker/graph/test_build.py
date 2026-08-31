"""Сборка StateGraph, чекпойнтер, durable resume — раздел 6 плана T1.5.1.

Все тесты работают на ``tmp_path`` с ``SqliteSaver.from_conn_string`` и не
ходят в сеть: профили в ``contract_01.docx`` собираются структурно (см.
``test_profile_judge.py``), ``RunDeps()`` без LLM хватает почти везде;
``FakeProvider`` нужен только там, где требуется вопрос вида "entity" —
все реальные сущности фикстуры уверенно детектируются (>= 0.8), порог
судьи (0.75) естественным путём не пробивается.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from masker.detect.agent import DetectAgent
from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.llm.fake import FakeProvider

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"

#: Ни одна сущность в contract_01.docx не набирает уверенность ниже порога
#: судьи (все правила/NER дают >= 0.8) — вопрос "entity" естественным путём
#: не возникает. Кандидат от LLM (Source.LLM, confidence <= 0.6) даёт его
#: детерминированно, без сети — FakeProvider.
_CANDIDATE_RESPONSE = (
    '{"profiles": [], "candidates": ['
    '{"segment_order": 0, "text": "44/2026", "type": "contract_number", "confidence": 0.6}'
    "]}"
)


def _options(*, interactive: bool, thread_id: str = "t1") -> dict[str, object]:
    return {
        "types": None,
        "rules_only": False,
        "interactive": interactive,
        "unmask_critical": False,
        "thread_id": thread_id,
    }


def _initial_state(*, interactive: bool, thread_id: str = "t1") -> dict[str, object]:
    return {"path": str(FIXTURE), "options": _options(interactive=interactive, thread_id=thread_id)}


def test_interactive_run_pauses_with_one_interrupt_before_finalize(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)

    interrupts = first.get("__interrupt__", ())
    assert len(interrupts) == 1
    assert "final_actions" not in first


def test_envelope_has_type_profile_and_entity_questions(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(llm=FakeProvider([_CANDIDATE_RESPONSE])), saver)
        first = graph.invoke(_initial_state(interactive=True), config)

    payload = first["__interrupt__"][0].value
    kinds = {question["kind"] for question in payload["questions"]}
    assert "type" in kinds
    assert "profile" in kinds
    assert "entity" in kinds


def test_durable_resume_survives_new_graph_and_saver_objects(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)

    payload = first["__interrupt__"][0].value
    answers = {question["id"]: question["default"] for question in payload["questions"]}
    # Конверт, не голый словарь: пустой/«плоский» resume-словарь без
    # обёртки трактуется langgraph как отсутствие значения (см. run.py).
    resume_value = {"schema_version": payload["schema_version"], "answers": answers}

    # Новый объект графа и новый SqliteSaver на том же файле — не тот же процесс.
    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        final = graph.invoke(Command(resume=resume_value), config)

    assert "__interrupt__" not in final
    assert final["final_actions"]
    assert {item["ref"] for item in final["final_actions"]}


def test_get_state_returns_same_envelope_without_re_running_nodes(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    calls = 0
    original_detect = DetectAgent.detect

    def counting_detect(self: DetectAgent, document: object) -> object:
        nonlocal calls
        calls += 1
        return original_detect(self, document)  # type: ignore[arg-type]

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=True), config)
    assert calls == 0  # детектор ещё не подменён — считаем честно с этой точки

    DetectAgent.detect = counting_detect  # type: ignore[method-assign]
    try:
        with SqliteSaver.from_conn_string(str(db)) as saver:
            graph = compile_graph(RunDeps(), saver)
            snapshot = graph.get_state(config)
    finally:
        DetectAgent.detect = original_detect  # type: ignore[method-assign]

    assert calls == 0
    assert len(snapshot.interrupts) == 1
    assert snapshot.interrupts[0].value == first["__interrupt__"][0].value


def test_non_interactive_run_finishes_in_one_invoke_without_interrupt(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        result = graph.invoke(_initial_state(interactive=False), config)

    assert "__interrupt__" not in result
    assert result["final_actions"]
    # Никто не спрашивал ни про тип, ни про профиль, ни про сущность — только
    # уверенность судьи и защита критичных типов могли повлиять на решение.
    decided_by = {item["decided_by"] for item in result["final_actions"]}
    assert decided_by <= {"judge", "default", "critical_guard"}
    assert decided_by & {"entity", "profile", "type"} == set()


def test_delete_thread_and_rerun_is_deterministic(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": "t1"}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        first = graph.invoke(_initial_state(interactive=False), config)

    with SqliteSaver.from_conn_string(str(db)) as saver:
        saver.delete_thread("t1")
        graph = compile_graph(RunDeps(), saver)
        second = graph.invoke(_initial_state(interactive=False), config)

    assert first["final_actions"] == second["final_actions"]


@pytest.mark.parametrize("thread_id", ["unknown-thread"])
def test_get_state_of_unknown_thread_has_no_interrupts(tmp_path: Path, thread_id: str) -> None:
    db = tmp_path / "state.sqlite"
    config = {"configurable": {"thread_id": thread_id}}

    with SqliteSaver.from_conn_string(str(db)) as saver:
        graph = compile_graph(RunDeps(), saver)
        snapshot = graph.get_state(config)

    assert snapshot.interrupts == ()
    assert snapshot.created_at is None
