"""Тесты графа компиляции пользовательских типов (план T1.13, шаг 11).

Ходит только в локальные `.docx` и SQLite на `tmp_path`, сети не требует.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from masker.customtypes.compiler import MAX_ASK_ROUNDS, clear_cache
from masker.customtypes.graph import (
    CompileAlreadyFinishedError,
    CompileDeps,
    UnknownCompileThreadError,
    resume_compile,
    start_compile,
)
from masker.llm import FakeProvider

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


@pytest.fixture(autouse=True)
def _clear_compiler_cache() -> None:
    """Кэш `compiler.py` — модульный процесс-синглтон (design notes, вопрос 5):
    без сброса между тестами одинаковые описания из разных тестов этого файла
    («замажь ФИО») отвечали бы из кэша, не трогая очередь `FakeProvider`."""
    clear_cache()
    yield
    clear_cache()


def _use_builtin(type_id: str) -> str:
    return json.dumps({"outcome": "use_builtin", "type_id": type_id, "marker_override": None})


def _compile(spec: dict[str, object]) -> str:
    return json.dumps({"outcome": "compile", "spec": spec})


def _ask(question: str, options: list[str] | None = None, target: str = "") -> str:
    return json.dumps(
        {"outcome": "ask", "question": question, "options": options or [], "target": target}
    )


def _factory(tmp_path: Path):
    from masker.run import sqlite_checkpointer_factory

    return sqlite_checkpointer_factory(tmp_path / "compile_state.sqlite")


_PRODUCT_CODE_SPEC: dict[str, object] = {
    "id": "product_code",
    "title": "Код товара",
    "marker": "[КОД-{n}]",
    "critical": False,
    "detect": {"kind": "literals", "values": ["SKU-42"]},
}


def test_single_use_builtin_finishes_without_pausing(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider([_use_builtin("person")])
    outcome = start_compile(
        FIXTURE,
        ["замажь ФИО"],
        thread_id=secrets.token_hex(8),
        checkpointer_factory=factory,
        deps=CompileDeps(llm=llm),
    )

    assert outcome.status == "done"
    items = outcome.state["items"]
    assert len(items) == 1
    assert items[0]["status"] == "compiled"
    assert items[0]["outcome_kind"] == "use_builtin"
    assert items[0]["type_id"] == "person"
    assert items[0].get("preview") is None


def test_compile_outcome_gets_real_preview_from_document(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider([_compile(_PRODUCT_CODE_SPEC)])
    outcome = start_compile(
        FIXTURE,
        ["замажь коды товара SKU-42"],
        thread_id=secrets.token_hex(8),
        checkpointer_factory=factory,
        deps=CompileDeps(llm=llm),
    )

    assert outcome.status == "done"
    item = outcome.state["items"][0]
    assert item["status"] == "compiled"
    assert item["outcome_kind"] == "compile"
    assert "preview" in item
    assert item["preview"]["total_matches"] == 0  # SKU-42 отсутствует в contract_01.docx
    assert item["preview"]["segments"]  # но образцы всё равно есть


def test_ask_outcome_pauses_graph_with_single_interrupt(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider(
        [_ask("Какую дату — отгрузки или подписания?", ["отгрузки", "подписания"], "T1")]
    )
    outcome = start_compile(
        FIXTURE,
        ["замажь дату"],
        thread_id=secrets.token_hex(8),
        checkpointer_factory=factory,
        deps=CompileDeps(llm=llm),
    )

    assert outcome.status == "waiting"
    assert outcome.payload is not None
    assert len(outcome.payload["questions"]) == 1
    assert outcome.payload["questions"][0]["text"] == "Какую дату — отгрузки или подписания?"


def test_resume_after_ask_reaches_preview(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider(
        [
            _ask("Какую дату?", ["отгрузки"], "T1"),
            _compile(
                {
                    "id": "shipment_date",
                    "title": "Дата отгрузки",
                    "marker": "[ДАТА-ОТГРУЗКИ-{n}]",
                    "critical": False,
                    "detect": {"kind": "regex", "pattern": r"\d{2}\.\d{2}\.\d{4}"},
                }
            ),
        ]
    )
    thread_id = secrets.token_hex(8)
    deps = CompileDeps(llm=llm)
    paused = start_compile(
        FIXTURE, ["замажь дату"], thread_id=thread_id, checkpointer_factory=factory, deps=deps
    )
    assert paused.status == "waiting"
    question_id = paused.payload["questions"][0]["id"]

    done = resume_compile(
        thread_id, {question_id: "отгрузки"}, checkpointer_factory=factory, deps=deps
    )

    assert done.status == "done"
    item = done.state["items"][0]
    assert item["status"] == "compiled"
    assert item["outcome_kind"] == "compile"
    assert item["spec"]["id"] == "shipment_date"


def test_three_ask_rounds_end_in_cannot_compile_not_a_fourth_question(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider([_ask(f"Вопрос {i}") for i in range(1, MAX_ASK_ROUNDS + 1)])
    thread_id = secrets.token_hex(8)
    deps = CompileDeps(llm=llm)

    outcome = start_compile(
        FIXTURE,
        ["замажь неоднозначное"],
        thread_id=thread_id,
        checkpointer_factory=factory,
        deps=deps,
    )
    interrupts = 0
    while outcome.status == "waiting":
        interrupts += 1
        question_id = outcome.payload["questions"][0]["id"]
        outcome = resume_compile(
            thread_id, {question_id: f"ответ {interrupts}"}, checkpointer_factory=factory, deps=deps
        )

    assert outcome.status == "done"
    item = outcome.state["items"][0]
    assert item["status"] == "failed"
    assert f"Вопрос {MAX_ASK_ROUNDS}" in item["reason"]
    # MAX_ASK_ROUNDS = 3 попытки компилятора, но не более MAX_ASK_ROUNDS - 1 прерываний:
    # на последней попытке compiler.compile_type сам не даёт четвёртого вопроса.
    assert interrupts == MAX_ASK_ROUNDS - 1
    assert llm.calls == MAX_ASK_ROUNDS


def test_partial_success_two_types_one_asks_one_compiles(tmp_path: Path) -> None:
    """Один тип сразу компилируется, другой спрашивает — вопросов одной пачкой,
    независимо завершённые типы не блокируются приостановленными."""
    factory = _factory(tmp_path)
    llm = FakeProvider(
        [
            _use_builtin("person"),
            _ask("Какая дата?", ["отгрузки"], "T2"),
        ]
    )
    thread_id = secrets.token_hex(8)
    deps = CompileDeps(llm=llm)

    outcome = start_compile(
        FIXTURE,
        ["замажь ФИО", "замажь дату"],
        thread_id=thread_id,
        checkpointer_factory=factory,
        deps=deps,
    )

    assert outcome.status == "waiting"
    assert len(outcome.payload["questions"]) == 1  # только по "asking"-типу


def test_resume_after_process_restart_reuses_sqlite_file(tmp_path: Path) -> None:
    """Новый чекпойнтер из того же файла (имитация перезапуска процесса)
    не теряет состояние приостановленной компиляции."""
    db_path = tmp_path / "compile_state.sqlite"

    def factory_a():
        from masker.run import sqlite_checkpointer_factory

        return sqlite_checkpointer_factory(db_path)()

    llm = FakeProvider(
        [
            _ask("Какая дата?", ["отгрузки"], "T1"),
            _use_builtin("date"),
        ]
    )
    thread_id = secrets.token_hex(8)
    deps = CompileDeps(llm=llm)

    with factory_a() as saver:
        from masker.customtypes.graph import compile_graph

        graph = compile_graph(deps, saver)
        result = graph.invoke(
            {"path": str(FIXTURE), "descriptions": ["замажь дату"]},
            {"configurable": {"thread_id": thread_id}},
        )
        assert result.get("__interrupt__")

    # "Перезапуск процесса": новый SqliteSaver из того же файла.
    def factory_b():
        return SqliteSaver.from_conn_string(str(db_path))

    question_id = "CT-0"
    outcome = resume_compile(
        thread_id, {question_id: "отгрузки"}, checkpointer_factory=factory_b, deps=deps
    )

    assert outcome.status == "done"
    assert outcome.state["items"][0]["status"] == "compiled"


def test_resume_unknown_thread_raises(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with pytest.raises(UnknownCompileThreadError):
        resume_compile(
            "does-not-exist", {}, checkpointer_factory=factory, deps=CompileDeps(llm=FakeProvider())
        )


def test_resume_on_finished_thread_raises(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    llm = FakeProvider([_use_builtin("person")])
    thread_id = secrets.token_hex(8)
    deps = CompileDeps(llm=llm)
    outcome = start_compile(
        FIXTURE, ["замажь ФИО"], thread_id=thread_id, checkpointer_factory=factory, deps=deps
    )
    assert outcome.status == "done"

    with pytest.raises(CompileAlreadyFinishedError):
        resume_compile(thread_id, {}, checkpointer_factory=factory, deps=deps)
