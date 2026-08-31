"""Сервис прогона: то, что поверх графа позовёт веб (раздел 5 плана T1.5.1).

Ровно две операции: ``start_run`` («начать прогон и получить вопросы») и
``resume_run`` («прислать ответы»). Логика узлов при переезде на веб не
трогается — меняется только вызывающий и чекпойнтер (``SqliteSaver`` →
серверный), поэтому чекпойнтер сюда приходит фабрикой, а не создаётся внутри.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.questions import SCHEMA_VERSION as ANSWERS_SCHEMA_VERSION
from masker.graph.state import State

#: Поднимается руками при изменении состава ``State`` — защита от чтения
#: устаревшего чекпойнта после правки кода (раздел 5 плана T1.5.1).
RUN_SCHEMA_VERSION = 1

CheckpointerFactory = Callable[[], AbstractContextManager[BaseCheckpointSaver[str]]]


class UnknownThreadError(Exception):
    """Тред с таким ``thread_id`` не существует в чекпойнтере."""


class AlreadyFinishedError(Exception):
    """Прогон уже завершён; повторные ответы или повторный старт не приняты."""


class ThreadExistsError(Exception):
    """Явно заданный ``thread_id`` уже занят прогоном другого файла/опций."""


@dataclass(frozen=True, slots=True)
class RunOptions:
    """Опции одного прогона — то, из чего детерминированно считается ``thread_id``.

    ``interactive`` в хэш не входит: неинтерактивный прогон всегда стартует
    со свежего треда (``--fresh`` по умолчанию для него в CLI), поэтому
    вопрос «пауза или нет» не должен создавать другой ``thread_id`` для того
    же документа и тех же опций отбора PII.
    """

    types: tuple[str, ...] | None = None
    rules_only: bool = False
    profile: bool = True
    unmask_critical: bool = False
    llm_config_id: str = ""
    interactive: bool = True

    def canonical(self) -> dict[str, Any]:
        """JSON-каноничная форма опций, влияющих на ``thread_id``."""
        return {
            "types": sorted(self.types) if self.types else None,
            "rules_only": self.rules_only,
            "profile": self.profile,
            "unmask_critical": self.unmask_critical,
            "llm_config_id": self.llm_config_id,
        }


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """Единый результат ``start_run``/``resume_run``."""

    status: Literal["waiting", "done"]
    thread_id: str
    payload: dict[str, Any] | None
    state: dict[str, Any] = field(default_factory=dict)


def thread_id_for(path: str | Path, options: RunOptions) -> str:
    """``sha256(RUN_SCHEMA_VERSION | sha256(файл) | канонизированные опции)[:16]``."""
    file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    canonical = json.dumps(options.canonical(), sort_keys=True, ensure_ascii=False)
    payload = f"{RUN_SCHEMA_VERSION}|{file_hash}|{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def sqlite_checkpointer_factory(db_path: Path) -> CheckpointerFactory:
    """Фабрика ``SqliteSaver`` для CLI: новый объект чекпойнтера на каждый вызов.

    Файл получает права ``0600`` до открытия sqlite3 — в нём лежит полный
    текст документа и все найденные PII. Сервер под веб подставит свой
    чекпойнтер: ``SqliteSaver`` однопоточный и не годится под конкурентные
    запросы.
    """

    def factory() -> AbstractContextManager[BaseCheckpointSaver[str]]:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if not db_path.exists():
            db_path.touch(mode=0o600)
        else:
            db_path.chmod(0o600)
        return SqliteSaver.from_conn_string(str(db_path))

    return factory


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _thread_status(snapshot: Any) -> Literal["unknown", "waiting", "done"]:
    if snapshot.created_at is None:
        return "unknown"
    if snapshot.interrupts:
        return "waiting"
    return "done"


def _initial_state(
    path: str | Path,
    options: RunOptions,
    thread_id: str,
    answers: dict[str, str] | None = None,
) -> State:
    state: State = {
        "path": str(path),
        "options": {
            **options.canonical(),
            "thread_id": thread_id,
            "interactive": options.interactive,
        },
    }
    if answers:
        # Ответы известны заранее (CLI `--answers` без `--ask`) — needs_human
        # видит непустой state["answers"] и не ставит граф на паузу вовсе,
        # прогон завершается за один invoke (раздел 5 плана T1.5.1).
        state["answers"] = dict(answers)
    return state


def _outcome_from_invoke_result(thread_id: str, result: dict[str, Any]) -> RunOutcome:
    interrupts = result.get("__interrupt__", ())
    if interrupts:
        return RunOutcome("waiting", thread_id, dict(interrupts[0].value), dict(result))
    return RunOutcome("done", thread_id, None, dict(result))


def start_run(
    path: str | Path,
    options: RunOptions,
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
    thread_id: str | None = None,
    fresh: bool = False,
    answers: dict[str, str] | None = None,
) -> RunOutcome:
    """Начать прогон (или вернуть вопросы уже приостановленного).

    ``answers``, заданный заранее (CLI ``--answers`` без ``--ask``),
    попадает в начальное состояние: если ответов достаточно, граф ни разу
    не встаёт на паузу — прогон завершается за один вызов.

    На приостановленном треде не выполняет узлы заново — вопросы читаются
    через ``get_state`` (пробой доказано: повторный ``invoke`` перезапускает
    граф с ``START``). На завершённом треде без ``fresh`` бросает
    ``AlreadyFinishedError``.
    """
    explicit = thread_id is not None
    tid: str = thread_id if thread_id is not None else thread_id_for(path, options)

    with checkpointer_factory() as saver:
        graph = compile_graph(deps or RunDeps(), saver)
        config = _config(tid)
        if fresh:
            saver.delete_thread(tid)
        status = _thread_status(graph.get_state(config))

        # Явно заданный thread_id — это «займи именно этот идентификатор для
        # нового прогона», а не механизм опроса: опрос уже идущего или
        # завершённого прогона под конкретным thread_id — дело resume_run/
        # read_questions. Автоматически выведенный id (thread_id=None) по
        # определению идемпотентен и сюда не попадает — иначе повторный
        # `--ask` без --thread-id ломался бы этой же проверкой.
        if explicit and not fresh and status != "unknown":
            raise ThreadExistsError(
                f"thread_id {tid!r} уже занят; для опроса используйте --resume, "
                "для нового прогона под этим id — --fresh"
            )
        if status == "waiting":
            snapshot = graph.get_state(config)
            return RunOutcome(
                "waiting", tid, dict(snapshot.interrupts[0].value), dict(snapshot.values)
            )
        if status == "done":
            raise AlreadyFinishedError(
                f"прогон {tid} уже завершён; для нового прогона используйте --fresh"
            )

        result = graph.invoke(_initial_state(path, options, tid, answers), config)
        return _outcome_from_invoke_result(tid, result)


def resume_run(
    thread_id: str,
    answers: dict[str, Any],
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> RunOutcome:
    """Прислать ответы на приостановленный прогон.

    Неизвестный ``thread_id`` не запускает новый прогон (в отличие от
    поведения самого LangGraph, см. раздел 2 плана T1.5.1): существование
    треда проверяется через ``get_state`` до вызова ``invoke``.
    """
    with checkpointer_factory() as saver:
        graph = compile_graph(deps or RunDeps(), saver)
        config = _config(thread_id)
        status = _thread_status(graph.get_state(config))
        if status == "unknown":
            raise UnknownThreadError(f"неизвестный thread_id: {thread_id!r}")
        if status == "done":
            raise AlreadyFinishedError(
                f"прогон {thread_id} уже завершён; для нового прогона используйте --fresh"
            )

        # Конверт, а не голый словарь: `Command(resume={})` с пустыми ответами
        # трактуется langgraph 1.2.11 как отсутствие значения, и узел ставится
        # на паузу заново вместо возобновления (проверено экспериментально).
        resume_value = {"schema_version": ANSWERS_SCHEMA_VERSION, "answers": dict(answers)}
        result = graph.invoke(Command(resume=resume_value), config)
        return _outcome_from_invoke_result(thread_id, result)


def read_questions(
    thread_id: str,
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> dict[str, Any]:
    """Прочитать конверт вопросов приостановленного треда без выполнения узлов."""
    with checkpointer_factory() as saver:
        graph = compile_graph(deps or RunDeps(), saver)
        snapshot = graph.get_state(_config(thread_id))
        status = _thread_status(snapshot)
        if status == "unknown":
            raise UnknownThreadError(f"неизвестный thread_id: {thread_id!r}")
        if status == "done":
            raise AlreadyFinishedError(f"прогон {thread_id} уже завершён")
        return dict(snapshot.interrupts[0].value)
