"""Сервис прогона run.py — раздел 5/шаг 8 плана T1.5.1.

Ходит только в локальные ``.docx`` и SQLite на ``tmp_path``, сети не требует.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from masker.detect.agent import DetectAgent
from masker.graph.nodes import RunDeps
from masker.run import (
    AlreadyFinishedError,
    RunFailedError,
    RunOptions,
    ThreadExistsError,
    UnknownThreadError,
    artifacts_of,
    read_questions,
    report_of,
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


def test_thread_id_for_custom_types_is_order_independent() -> None:
    first = {"id": "shipment_date", "detect": {"kind": "regex", "pattern": "x"}}
    second = {"detect": {"values": ["SKU-42"], "kind": "literals"}, "id": "product_code"}
    a = thread_id_for(FIXTURE, RunOptions(custom_types=(first, second)))
    b = thread_id_for(
        FIXTURE,
        RunOptions(
            custom_types=(
                {"id": "product_code", "detect": {"kind": "literals", "values": ["SKU-42"]}},
                {"detect": {"pattern": "x", "kind": "regex"}, "id": "shipment_date"},
            )
        ),
    )
    assert a == b
    assert a != thread_id_for(FIXTURE, RunOptions(custom_types=(first,)))


def test_thread_id_for_changes_with_rules_only() -> None:
    a = thread_id_for(FIXTURE, RunOptions(rules_only=True))
    b = thread_id_for(FIXTURE, RunOptions(rules_only=False))
    assert a != b


def test_thread_id_for_changes_with_unmask_critical() -> None:
    a = thread_id_for(FIXTURE, RunOptions(unmask_critical=True))
    b = thread_id_for(FIXTURE, RunOptions(unmask_critical=False))
    assert a != b


def test_thread_id_for_does_not_depend_on_styles_or_preview() -> None:
    """T1.10, шаг 8: ``styles``/``preview`` не входят в ``canonical()``.

    Повторный ``--ask`` того же документа с теми же опциями отбора PII
    обязан попасть в тот же тред независимо от того, какие артефакты на
    выходе попросили в этот раз.
    """
    baseline = thread_id_for(FIXTURE, RunOptions())
    with_styles = thread_id_for(FIXTURE, RunOptions(styles=("marker", "blackbox")))
    without_preview = thread_id_for(FIXTURE, RunOptions(preview=False))
    assert baseline == with_styles == without_preview


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

    deps = RunDeps(artifact_dir=tmp_path / "artifacts")
    outcome = start_run(FIXTURE, options, checkpointer_factory=factory, deps=deps)
    assert outcome.status == "done"

    with pytest.raises(AlreadyFinishedError):
        resume_run(
            outcome.thread_id, {"TYPE-inn": "оставить"}, checkpointer_factory=factory, deps=deps
        )

    # `--ask` (start_run) на завершённом треде — тоже код 3, без --fresh.
    with pytest.raises(AlreadyFinishedError):
        start_run(FIXTURE, options, checkpointer_factory=factory, deps=deps)

    replay = start_run(FIXTURE, options, checkpointer_factory=factory, deps=deps, fresh=True)
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

    done = resume_run(
        paused.thread_id,
        {},
        checkpointer_factory=factory,
        deps=RunDeps(artifact_dir=tmp_path / "artifacts"),
    )

    assert done.status == "done"
    assert set(done.state["decisions"]["unanswered_defaults"]) == question_ids


def test_state_db_file_has_0600_permissions(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "state.sqlite"
    factory = sqlite_checkpointer_factory(db_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=False)

    start_run(
        FIXTURE,
        options,
        checkpointer_factory=factory,
        deps=RunDeps(artifact_dir=tmp_path / "artifacts"),
    )

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


def test_start_run_with_pre_supplied_answers_finishes_without_pausing(tmp_path: Path) -> None:
    """``--answers`` без ``--ask``: ответы известны заранее, паузы не возникает."""
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=True)

    peek = start_run(FIXTURE, options, checkpointer_factory=factory)
    assert peek.status == "waiting"
    assert peek.payload is not None
    answers = {question["id"]: question["default"] for question in peek.payload["questions"]}

    done = start_run(
        FIXTURE,
        options,
        checkpointer_factory=factory,
        fresh=True,
        answers=answers,
        deps=RunDeps(artifact_dir=tmp_path / "artifacts"),
    )

    assert done.status == "done"
    assert done.state["final_actions"]


def test_start_run_with_missing_artifact_dir_and_styles_raises_run_failed_error(
    tmp_path: Path,
) -> None:
    """``render_node`` роняет голый ``ValueError`` — ``run.py`` обязан обернуть его.

    Без обёртки CLI получил бы «загадочный трейсбек» из недр LangGraph
    вместо доменной ошибки прогона (раздел 5 плана T1.10).
    """
    factory = _factory(tmp_path)
    options = RunOptions(
        rules_only=True, types=("inn",), interactive=False, styles=("marker", "blackbox")
    )

    with pytest.raises(RunFailedError) as excinfo:
        start_run(FIXTURE, options, checkpointer_factory=factory, deps=RunDeps())

    assert excinfo.value.node_hint == "render"
    assert isinstance(excinfo.value.cause, ValueError)


def test_report_of_and_artifacts_of_are_non_empty_after_completed_run(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    options = RunOptions(rules_only=True, types=("inn",), interactive=False)
    deps = RunDeps(artifact_dir=tmp_path / "artifacts")

    outcome = start_run(FIXTURE, options, checkpointer_factory=factory, deps=deps)

    assert outcome.status == "done"
    report = report_of(outcome)
    artifacts = artifacts_of(outcome)
    assert report
    assert report["report_version"] == 3
    assert artifacts
    assert artifacts[0]["role"] == "preview"
