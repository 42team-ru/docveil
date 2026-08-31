"""Сервис прогона run.py — раздел 5/шаг 8 плана T1.5.1.

Ходит только в локальные ``.docx`` и SQLite на ``tmp_path``, сети не требует.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from masker.detect.agent import DetectAgent
from masker.run import (
    AlreadyFinishedError,
    RunOptions,
    ThreadExistsError,
    UnknownThreadError,
    read_questions,
    resume_run,
    sqlite_checkpointer_factory,
    start_run,
    thread_id_for,
)

ROOT = next(
    parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()
)
FIXTURE = ROOT / "fixtures" / "labeled" / "contract_01.docx"


def _factory(tmp_path: Path):
    return sqlite_checkpointer_factory(tmp_path / "state.sqlite")


def test_thread_id_for_is_stable_across_calls() -> None:
    options = RunOptions(types=("inn", "phone"))
    first = thread_id_for(FIXTURE, options)
    second = thread_id_for(FIXTURE, options)
    assert first == second
    assert len(first) == 16


def test_thread_id_for_is_order_independent_for_types() -> None:
    a = thread_id_for(FIXTURE, RunOptions(types=("inn", "phone")))
    b = thread_id_for(FIXTURE, RunOptions(types=("phone", "inn")))
    assert a == b


def test_thread_id_for_changes_with_types() -> None:
    a = thread_id_for(FIXTURE, RunOptions(types=("inn",)))
    b = thread_id_for(FIXTURE, RunOptions(types=("phone",)))
    assert a != b


def test_thread_id_for_changes_with_rules_only() -> None:
    a = thread_id_for(FIXTURE, RunOptions(rules_only=True))
    b = thread_id_for(FIXTURE, RunOptions(rules_only=False))
    assert a != b


def test_thread_id_for_changes_with_unmask_critical() -> None:
    a = thread_id_for(FIXTURE, RunOptions(unmask_critical=True))
    b = thread_id_for(FIXTURE, RunOptions(unmask_critical=False))
    assert a != b


def test_thread_id_for_changes_with_schema_version(monkeypatch: pytest.MonkeyPatch) -> None:
    import masker.run as run_module

    before = thread_id_for(FIXTURE, RunOptions())
    monkeypatch.setattr(run_module, "RUN_SCHEMA_VERSION", run_module.RUN_SCHEMA_VERSION + 1)
    after = thread_id_for(FIXTURE, RunOptions())
    assert before != after


def test_resume_run_unknown_thread_raises_and_does_not_create_thread(tmp_path: Path) -> None:
    factory = _factory(tmp_path)

    with pytest.raises(UnknownThreadError):
        resume_run("does-not-exist", {}, checkpointer_factory=factory)

    with factory() as saver:
        from masker.graph.build import compile_graph
        from masker.graph.nodes import RunDeps

        graph = compile_graph(RunDeps(), saver)
        snapshot = graph.get_state({"configurable": {"thread_id": "does-not-exist"}})
    assert snapshot.created_at is None


def test_resume_run_on_finished_thread_raises_and_state_unchanged(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=False)

    outcome = start_run(FIXTURE, options, checkpointer_factory=factory)
    assert outcome.status == "done"

    with pytest.raises(AlreadyFinishedError):
        resume_run(outcome.thread_id, {"TYPE-inn": "оставить"}, checkpointer_factory=factory)

    # `--ask` (start_run) на завершённом треде — тоже код 3, без --fresh.
    with pytest.raises(AlreadyFinishedError):
        start_run(FIXTURE, options, checkpointer_factory=factory)

    replay = start_run(FIXTURE, options, checkpointer_factory=factory, fresh=True)
    assert replay.thread_id == outcome.thread_id
    assert replay.state["final_actions"] == outcome.state["final_actions"]


def test_start_run_on_waiting_thread_returns_same_payload_without_running_detector(
    tmp_path: Path,
) -> None:
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=True)

    first = start_run(FIXTURE, options, checkpointer_factory=factory)
    assert first.status == "waiting"

    calls = 0
    original_detect = DetectAgent.detect

    def counting_detect(self: DetectAgent, document: object) -> object:
        nonlocal calls
        calls += 1
        return original_detect(self, document)  # type: ignore[arg-type]

    DetectAgent.detect = counting_detect  # type: ignore[method-assign]
    try:
        second = start_run(FIXTURE, options, checkpointer_factory=factory)
    finally:
        DetectAgent.detect = original_detect  # type: ignore[method-assign]

    assert calls == 0
    assert second.payload == first.payload
    assert second.thread_id == first.thread_id


def test_missing_answers_use_defaults_and_are_reported(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=True)

    paused = start_run(FIXTURE, options, checkpointer_factory=factory)
    assert paused.payload is not None
    question_ids = {question["id"] for question in paused.payload["questions"]}

    done = resume_run(paused.thread_id, {}, checkpointer_factory=factory)

    assert done.status == "done"
    assert set(done.state["decisions"]["unanswered_defaults"]) == question_ids


def test_state_db_file_has_0600_permissions(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "state.sqlite"
    factory = sqlite_checkpointer_factory(db_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=False)

    start_run(FIXTURE, options, checkpointer_factory=factory)

    assert db_path.is_file()
    assert stat.S_IMODE(db_path.stat().st_mode) == 0o600


def test_thread_exists_error_when_explicit_id_reused_without_fresh(tmp_path: Path) -> None:
    """Явный ``thread_id`` — «займи этот id для нового прогона», не опрос.

    Опрос уже идущего/завершённого прогона под известным id — дело
    ``resume_run``/``read_questions``; автоматически выведенный id
    (``thread_id=None``) под эту проверку не попадает — иначе повторный
    ``--ask`` без ``--thread-id`` (идемпотентный по контракту) ломался бы
    этой же защитой.
    """
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=True)

    started = start_run(FIXTURE, options, checkpointer_factory=factory)
    assert started.status == "waiting"

    with pytest.raises(ThreadExistsError):
        start_run(
            FIXTURE,
            options,
            checkpointer_factory=factory,
            thread_id=started.thread_id,
        )

    # С --fresh тот же явный id разрешён — запускает заново.
    restarted = start_run(
        FIXTURE, options, checkpointer_factory=factory, thread_id=started.thread_id, fresh=True
    )
    assert restarted.status == "waiting"


def test_read_questions_matches_start_run_payload_without_reinvoking(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=True)

    paused = start_run(FIXTURE, options, checkpointer_factory=factory)
    payload = read_questions(paused.thread_id, checkpointer_factory=factory)

    assert payload == paused.payload


def test_read_questions_unknown_thread_raises(tmp_path: Path) -> None:
    factory = _factory(tmp_path)

    with pytest.raises(UnknownThreadError):
        read_questions("does-not-exist", checkpointer_factory=factory)


def test_sqlite_checkpointer_factory_reuses_existing_saver_type(tmp_path: Path) -> None:
    factory = sqlite_checkpointer_factory(tmp_path / "db.sqlite")
    with factory() as saver:
        assert isinstance(saver, SqliteSaver)
