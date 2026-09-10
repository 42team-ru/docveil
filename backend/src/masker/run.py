"""Сервис прогона: то, что поверх графа позовёт веб (раздел 5 плана T1.5.1).

Ровно две операции: ``start_run`` («начать прогон и получить вопросы») и
``resume_run`` («прислать ответы»). Логика узлов при переезде на веб не
трогается — меняется только вызывающий и чекпойнтер (``SqliteSaver`` →
серверный), поэтому чекпойнтер сюда приходит фабрикой, а не создаётся внутри.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from masker.graph.build import compile_graph
from masker.graph.nodes import RunDeps
from masker.graph.questions import SCHEMA_VERSION as ANSWERS_SCHEMA_VERSION
from masker.graph.review import SCHEMA_VERSION as REVIEW_SCHEMA_VERSION
from masker.graph.state import State
from masker.highlight import DEFAULT_HIGHLIGHT_BACKGROUND, parse_highlight_background
from masker.telemetry import RUNTIME_METRICS_NAME, runtime_metrics

#: Поднимается руками при изменении состава ``State`` — защита от чтения
#: устаревшего чекпойнта после правки кода (раздел 5 плана T1.5.1).
RUN_SCHEMA_VERSION = 1

CheckpointerFactory = Callable[[], AbstractContextManager[BaseCheckpointSaver[str]]]


def styles_for_redact_option(style: str | None) -> tuple[str, ...]:
    """Преобразовать значение CLI-стиля в набор рендеров графа."""
    if style is None:
        return ()
    return {
        "marker": ("marker",),
        "blackbox": ("blackbox",),
        "both": ("marker", "blackbox"),
    }.get(style, ())


class UnknownThreadError(Exception):
    """Тред с таким ``thread_id`` не существует в чекпойнтере."""


class AlreadyFinishedError(Exception):
    """Прогон уже завершён; повторные ответы или повторный старт не приняты."""


class ThreadExistsError(Exception):
    """Явно заданный ``thread_id`` уже занят прогоном другого файла/опций."""


#: LangGraph добавляет к исключению узла заметку вида «During task with
#: name 'render' and id '...'» (PEP 678, ``__notes__``) перед тем, как
#: поднять его выше по стеку — единственный способ узнать, какой узел упал,
#: не трогая внутренности узлов.
_TASK_NAME_RE = re.compile(r"During task with name '([^']+)'")


def _node_hint(error: Exception) -> str:
    """Имя узла-виновника из ``__notes__`` исключения; ``"unknown"``, если нет."""
    for note in getattr(error, "__notes__", None) or ():
        match = _TASK_NAME_RE.search(note)
        if match:
            return match.group(1)
    return "unknown"


class RunFailedError(Exception):
    """``graph.invoke`` уронил ``OSError``/``ValueError`` изнутри узла графа.

    Узлы графа ничего не глотают (``render_node`` — нет каталога/диска,
    неизвестный стиль; см. раздел 5 плана T1.10). ``run.py`` — единственное
    место, которое обязано превратить сырое исключение LangGraph в доменную
    ошибку прогона, а не дать ``ValueError`` из недр графа всплыть до CLI
    как загадочный трейсбек.
    """

    def __init__(self, thread_id: str, node_hint: str, cause: Exception) -> None:
        super().__init__(f"прогон {thread_id} упал в узле {node_hint!r}: {cause}")
        self.thread_id = thread_id
        self.node_hint = node_hint
        self.cause = cause


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
    #: Подмножество ``("marker", "blackbox")`` — какие редактирующие рендеры
    #: строит ``render_node``. Вне ``canonical()``: не меняет отбор PII,
    #: поэтому повторный ``--ask`` того же документа обязан попасть в тот же
    #: тред независимо от того, какие артефакты попросили на выходе
    #: (раздел 4 плана T1.10).
    styles: tuple[str, ...] = ()
    #: Рендерить ли ``preview.*``. Вне ``canonical()`` по той же причине.
    preview: bool = True
    #: Фон читаемой маски: ``#RRGGBB`` либо ``None`` (явное ``none``).
    #: В отличие от ``styles`` фон меняет сами артефакты и поэтому входит
    #: в ``canonical()``/``thread_id``.
    highlight_background: str | None = DEFAULT_HIGHLIGHT_BACKGROUND
    #: Останавливаться ли после отчёта на правках оператора (второе
    #: прерывание графа, ``ask_review``). Вне ``canonical()``: раунд правок
    #: не меняет отбор PII, поэтому не обязан разводить треды.
    review: bool = False
    #: Скомпилированные JSON-спеки пользовательских типов. Объекты с
    #: ``re.Pattern`` в State не кладём: они не сериализуются чекпойнтером.
    custom_types: tuple[dict[str, Any], ...] = ()
    #: Формат вывода для прогонов, начавшихся с картинки:
    #: ``"original"`` — вернуть JPEG/PNG/TIFF того же расширения, что вход;
    #: ``"pdf"`` — отдать одностраничный PDF-артефакт как есть. **Входит в
    #: ``canonical()``**: разные форматы вывода — разные прогоны (API-контракт
    #: №2 — feat/api-runs). Для не-картиночных входов значение игнорируется.
    image_output_format: Literal["original", "pdf"] = "original"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "highlight_background", parse_highlight_background(self.highlight_background)
        )

    def canonical(self) -> dict[str, Any]:
        """JSON-каноничная форма опций, влияющих на ``thread_id``."""
        custom_types = sorted(
            (
                json.loads(json.dumps(item, sort_keys=True, ensure_ascii=False))
                for item in self.custom_types
            ),
            key=lambda item: str(item.get("id", "")),
        )
        return {
            "types": sorted(self.types) if self.types else None,
            "rules_only": self.rules_only,
            "profile": self.profile,
            "unmask_critical": self.unmask_critical,
            "llm_config_id": self.llm_config_id,
            "highlight_background": self.highlight_background,
            "custom_types": custom_types,
            "image_output_format": self.image_output_format,
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


def postgres_checkpointer_factory(dsn: str) -> CheckpointerFactory:
    """Фабрика ``PostgresSaver`` для веб-сервера: новый чекпойнтер на запрос.

    ``SqliteSaver`` однопоточный и под конкурентные HTTP-запросы не годится —
    это ровно тот «серверный чекпойнтер», о котором говорит docstring
    ``sqlite_checkpointer_factory``. Логика узлов от подмены не меняется:
    фабрика приходит снаружи, как и раньше (требование заказчика №6).

    ``dsn`` — обычная строка psycopg (``postgresql://…``). SQLAlchemy-диалект
    (``postgresql+asyncpg://``) сюда не годится: у saver'а свой синхронный
    драйвер, поэтому строка нормализуется здесь, а не у вызывающего.

    Таблицы чекпойнтера создаёт ``setup()`` — один раз на процесс: повторный
    вызов на каждый запрос стоит нескольких DDL-запросов на ровном месте.
    """
    conn_string = _psycopg_dsn(dsn)

    def factory() -> AbstractContextManager[BaseCheckpointSaver[str]]:
        return _PostgresCheckpointerContext(conn_string)

    return factory


def _psycopg_dsn(dsn: str) -> str:
    """``postgresql+asyncpg://…`` → ``postgresql://…``; прочее — без изменений."""
    scheme, separator, rest = dsn.partition("://")
    if not separator:
        raise ValueError(f"строка подключения без схемы: {dsn!r}")
    return f"{scheme.partition('+')[0]}://{rest}"


#: ``thread-safe``-множество DSN, для которых ``PostgresSaver.setup()`` уже
#: отработал в этом процессе. Ключ — DSN, а не сам saver: объект чекпойнтера
#: создаётся заново на каждый запрос, а таблицы в базе — общие.
_POSTGRES_SETUP_DONE: set[str] = set()
_POSTGRES_SETUP_LOCK = Lock()


class _PostgresCheckpointerContext(AbstractContextManager[BaseCheckpointSaver[str]]):
    """``PostgresSaver.from_conn_string`` плюс однократный ``setup()`` на DSN."""

    def __init__(self, conn_string: str) -> None:
        self._conn_string = conn_string
        self._inner: AbstractContextManager[PostgresSaver] | None = None

    def __enter__(self) -> BaseCheckpointSaver[str]:
        self._inner = PostgresSaver.from_conn_string(self._conn_string)
        saver = self._inner.__enter__()
        with _POSTGRES_SETUP_LOCK:
            if self._conn_string not in _POSTGRES_SETUP_DONE:
                saver.setup()
                _POSTGRES_SETUP_DONE.add(self._conn_string)
        return saver

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        inner, self._inner = self._inner, None
        if inner is not None:
            inner.__exit__(exc_type, exc, tb)  # type: ignore[arg-type]


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
            "styles": list(options.styles),
            "preview": options.preview,
            "review": options.review,
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


def _write_runtime_metrics(outcome: RunOutcome, deps: RunDeps) -> RunOutcome:
    """Записать недетерминированные замеры отдельным артефактом прогона."""
    if deps.artifact_dir is None or "report" not in outcome.state:
        return outcome
    telemetry = outcome.state.get("telemetry")
    if not isinstance(telemetry, dict):
        return outcome
    destination = deps.artifact_dir / RUNTIME_METRICS_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(runtime_metrics(telemetry), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    destination.chmod(0o600)
    artifacts = list(outcome.state.get("artifacts", []))
    if not any(item.get("role") == "runtime_metrics" for item in artifacts):
        artifacts.append(
            {
                "role": "runtime_metrics",
                "name": RUNTIME_METRICS_NAME,
                "path": str(destination),
                "redacting": False,
            }
        )
        outcome.state["artifacts"] = artifacts
    return outcome


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

        try:
            result = graph.invoke(_initial_state(path, options, tid, answers), config)
        except (OSError, ValueError) as error:
            raise RunFailedError(tid, _node_hint(error), error) from error
        return _write_runtime_metrics(_outcome_from_invoke_result(tid, result), deps or RunDeps())


def resume_run(
    thread_id: str,
    answers: dict[str, Any],
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> RunOutcome:
    """Прислать ответы на вопросы приостановленного прогона (``ask_human``).

    Неизвестный ``thread_id`` не запускает новый прогон (в отличие от
    поведения самого LangGraph, см. раздел 2 плана T1.5.1): существование
    треда проверяется через ``get_state`` до вызова ``invoke``.
    """
    # Конверт, а не голый словарь: `Command(resume={})` с пустыми ответами
    # трактуется langgraph 1.2.11 как отсутствие значения, и узел ставится
    # на паузу заново вместо возобновления (проверено экспериментально).
    return _resume(
        thread_id,
        {"schema_version": ANSWERS_SCHEMA_VERSION, "answers": dict(answers)},
        checkpointer_factory=checkpointer_factory,
        deps=deps,
    )


def resume_review(
    thread_id: str,
    edits: dict[str, Any],
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> RunOutcome:
    """Прислать правки оператора на паузу раунда проверки (``ask_review``).

    Отдельная функция, а не флаг у ``resume_run``: у двух прерываний графа
    два разных конверта со своими версиями схемы, и подставлять конверт
    ответов в узел правок — молча получить ``ValueError`` из недр графа.
    """
    return _resume(
        thread_id,
        {"schema_version": REVIEW_SCHEMA_VERSION, "edits": dict(edits)},
        checkpointer_factory=checkpointer_factory,
        deps=deps,
    )


def _resume(
    thread_id: str,
    resume_value: dict[str, Any],
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> RunOutcome:
    """Общее тело возобновления: проверка треда и один ``invoke``."""
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

        try:
            result = graph.invoke(Command(resume=resume_value), config)
        except (OSError, ValueError) as error:
            raise RunFailedError(thread_id, _node_hint(error), error) from error
        return _write_runtime_metrics(
            _outcome_from_invoke_result(thread_id, result), deps or RunDeps()
        )


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


def read_run(
    thread_id: str,
    *,
    checkpointer_factory: CheckpointerFactory,
    deps: RunDeps | None = None,
) -> RunOutcome:
    """Прочитать состояние треда, не выполняя узлов графа.

    Симметрична ``read_questions``, но отдаёт весь ``RunOutcome`` — из него
    те же ``report_of``/``artifacts_of`` достают отчёт и артефакты. Нужна
    вызывающему, который спрашивает «чем кончился прогон» отдельным запросом
    (веб опрашивает статус), а не держит ``RunOutcome`` от ``start_run``.
    """
    with checkpointer_factory() as saver:
        graph = compile_graph(deps or RunDeps(), saver)
        snapshot = graph.get_state(_config(thread_id))
        status = _thread_status(snapshot)
        if status == "unknown":
            raise UnknownThreadError(f"неизвестный thread_id: {thread_id!r}")
        if status == "waiting":
            return RunOutcome(
                "waiting", thread_id, dict(snapshot.interrupts[0].value), dict(snapshot.values)
            )
        return RunOutcome("done", thread_id, None, dict(snapshot.values))


def report_of(outcome: RunOutcome) -> dict[str, Any]:
    """Структура ``report.json`` из состояния завершённого прогона.

    Тонкий аксессор, не предметная логика: ``report_node`` уже собрал
    структуру внутри графа (T1.10, шаг 7) — здесь только чтение поля.
    На приостановленном прогоне (``status == "waiting"``) узел ``report``
    ещё не выполнялся — возвращается пустой словарь.
    """
    return dict(outcome.state.get("report", {}))


def artifacts_of(outcome: RunOutcome) -> list[dict[str, Any]]:
    """Записанные на диск артефакты (``role``/``name``/``path``/``redacting``)
    из состояния завершённого прогона — см. ``render_node`` (T1.10, шаг 5)."""
    return list(outcome.state.get("artifacts", []))
