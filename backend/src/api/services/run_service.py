"""Связка REST-эндпоинтов маскирования с графом `masker.run` (веб вместо CLI).

Ровно то, что обещано в T1.5.1: «переезд CLI → веб меняет только вызывающего
и чекпойнтер, а не логику узлов». Здесь живут скачивание документа из MinIO,
выбор чекпойнтера, фоновое выполнение и запись метаданных прогона в Postgres.
Предметной логики (отбор типов, решения по сущностям, сборка отчёта) здесь
нет и быть не должно — она вся в узлах графа.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.db import async_session_maker
from api.core.storage import minio_client
from api.models.run import RunORM
from api.schemas.run import RunCreateRequest
from masker.graph.nodes import RunDeps
from masker.ingest import SUPPORTED_SUFFIXES as ENGINE_SUFFIXES
from masker.llm import LLMProvider, get_provider, resolve_llm_config
from masker.run import (
    AlreadyFinishedError,
    CheckpointerFactory,
    RunFailedError,
    RunOptions,
    RunOutcome,
    UnknownThreadError,
    artifacts_of,
    postgres_checkpointer_factory,
    read_run,
    report_of,
    resume_review,
    resume_run,
    sqlite_checkpointer_factory,
    start_run,
)

__all__ = [
    "AlreadyFinishedError",
    "RunOutcome",
    "UnknownThreadError",
    "UnsupportedFormatError",
    "artifact_bytes",
    "create_run",
    "execute_run",
    "get_llm_provider",
    "get_run_checkpointer_factory",
    "list_artifacts",
    "list_runs",
    "read_outcome",
    "resume_with_answers",
    "resume_with_review",
    "run_report",
]

#: `--redact-style` веба: то же соответствие, что у CLI (`masker.cli`).
_STYLES_BY_MASK_STYLE: dict[str, tuple[str, ...]] = {
    "marker": ("marker",),
    "blackbox": ("blackbox",),
    "both": ("marker", "blackbox"),
}

#: Единственный источник — слой разбора движка (`masker.ingest`). Свой
#: список здесь однажды уже разошёлся с движком: XLSX работал в воротах и
#: отдавал 422 через API.
SUPPORTED_SUFFIXES = ENGINE_SUFFIXES


class UnsupportedFormatError(Exception):
    """Формат документа движок не обрабатывает — прогон не заводится вовсе."""


def get_llm_provider() -> LLMProvider:
    """FastAPI-зависимость: провайдер LLM прогона.

    Только через `masker.llm.get_provider()` (требование заказчика №6):
    подмена GigaChat/OpenRouter/Fake — вопрос окружения процесса, не кода.
    """
    return get_provider()


def get_run_checkpointer_factory() -> CheckpointerFactory:
    """FastAPI-зависимость: чекпойнтер графа маскирования.

    По умолчанию Postgres: `SqliteSaver` однопоточный и под конкурентные
    запросы не годится (`masker.run.sqlite_checkpointer_factory`). Режим
    `sqlite` включается настройкой явно — для локального запуска без базы.
    """
    if settings.run_checkpointer == "sqlite":
        return sqlite_checkpointer_factory(settings.run_state_db)
    return postgres_checkpointer_factory(settings.database_url)


def _document_format(object_name: str) -> str:
    suffix = Path(object_name).suffix.casefold()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedFormatError(
            f"формат {suffix or '<без расширения>'} не поддерживается; "
            f"допустимы: {', '.join(sorted(SUPPORTED_SUFFIXES))}"
        )
    return suffix.lstrip(".")


def _document_name(object_name: str) -> str:
    """Имя файла без uuid-префикса, которым `file_service` разводит объекты."""
    return Path(object_name).name


def _run_options(request: RunCreateRequest, document_format: str) -> RunOptions:
    return RunOptions(
        types=tuple(request.types) if request.types else None,
        rules_only=request.rules_only,
        # Профили и человек-в-цикле для PDF не реализованы (см. `masker.cli`):
        # запрошенный профиль на pdf молча не включаем, а гасим здесь явно.
        profile=request.profile and document_format != "pdf",
        unmask_critical=request.unmask_critical,
        interactive=True,
        styles=_STYLES_BY_MASK_STYLE[request.mask_style],
        preview=True,
        review=request.review,
        custom_types=tuple(request.custom_types),
    )


async def create_run(
    session: AsyncSession, user_id: uuid.UUID, request: RunCreateRequest
) -> RunORM:
    """Завести прогон в состоянии `queued`; сам граф стартует фоновой задачей.

    `thread_id` случайный, а не `thread_id_for(файл, опции)`: детерминированный
    id склеил бы два независимых прогона одного документа в один тред, и второй
    получил бы `AlreadyFinishedError` вместо своего прогона.
    """
    document_format = _document_format(request.object_name)
    run = RunORM(
        id=uuid.uuid4(),
        user_id=user_id,
        thread_id=secrets.token_hex(16),
        object_name=request.object_name,
        document_name=_document_name(request.object_name),
        document_format=document_format,
        options=request.model_dump(mode="json"),
        status="queued",
        created_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    return run


async def list_runs(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    query: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[RunORM], int]:
    """Журнал обработок пользователя: страница строк и общее число."""
    conditions = [RunORM.user_id == user_id]
    if query:
        conditions.append(RunORM.document_name.ilike(f"%{query}%"))
    if status:
        conditions.append(RunORM.status == status)

    rows = await session.execute(
        select(RunORM)
        .where(*conditions)
        .order_by(RunORM.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(select(func.count()).select_from(RunORM).where(*conditions))
    return list(rows.scalars()), int(total or 0)


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> RunORM | None:
    """Прогон пользователя по id; чужой прогон не отдаётся (тот же `None`)."""
    run: RunORM | None = await session.scalar(
        select(RunORM).where(RunORM.id == run_id, RunORM.user_id == user_id)
    )
    return run


def read_outcome(thread_id: str, *, checkpointer_factory: CheckpointerFactory) -> RunOutcome:
    """Состояние треда без выполнения узлов (`masker.run.read_run`)."""
    return read_run(thread_id, checkpointer_factory=checkpointer_factory)


def run_report(thread_id: str, *, checkpointer_factory: CheckpointerFactory) -> dict[str, Any]:
    """`report.json` прогона — тонкий аксессор к состоянию графа."""
    return report_of(read_outcome(thread_id, checkpointer_factory=checkpointer_factory))


def list_artifacts(
    thread_id: str, *, checkpointer_factory: CheckpointerFactory
) -> list[dict[str, Any]]:
    """Артефакты рендера (`role`/`name`/`redacting`) из состояния графа."""
    return artifacts_of(read_outcome(thread_id, checkpointer_factory=checkpointer_factory))


def artifact_prefix_of(run_id: uuid.UUID) -> str:
    return f"runs/{run_id}/"


def artifact_bytes(run_id: uuid.UUID, name: str) -> bytes:
    """Скачать артефакт прогона из MinIO."""
    response = minio_client.get_object(settings.minio_bucket, f"{artifact_prefix_of(run_id)}{name}")
    try:
        return bytes(response.read())
    finally:
        response.close()
        response.release_conn()


def _work_dir(run_id: uuid.UUID) -> Path:
    """Каталог прогона: исходный документ и файлы рендера до конца прогона.

    Каталог переживает паузу на вопросах: в состоянии графа лежит путь до
    документа (`state["path"]`), и на возобновлении узел `render` открывает
    именно его. Временный файл на один HTTP-запрос здесь не годится — после
    ответа `202` он бы исчез, и `resume` упал бы на несуществующем файле.
    """
    return Path(tempfile.gettempdir()) / "triema-runs" / str(run_id)


def _ensure_document(run_id: uuid.UUID, object_name: str) -> Path:
    """Скачать документ прогона в его рабочий каталог (повторно — не скачивает).

    Имя файла сохраняется как есть, а не заменяется на `document.docx`: из
    него движок берёт `meta.name`, и оно уходит в `report.input` — оператор
    обязан увидеть в отчёте имя своего документа. `Path.name` отрезает любые
    каталоги, поэтому выйти из рабочего каталога именем объекта нельзя.
    """
    work_dir = _work_dir(run_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    document = work_dir / _document_name(object_name)
    if not document.exists():
        minio_client.fget_object(settings.minio_bucket, object_name, str(document))
    return document


def _upload_artifacts(run_id: uuid.UUID, artifacts: list[dict[str, Any]]) -> str:
    """Выгрузить файлы рендера в MinIO под `runs/{run_id}/` и вернуть префикс."""
    prefix = artifact_prefix_of(run_id)
    for artifact in artifacts:
        path = Path(str(artifact["path"]))
        minio_client.fput_object(settings.minio_bucket, f"{prefix}{path.name}", str(path))
    return prefix


def _status_of(outcome: RunOutcome) -> str:
    """`RunOutcome` → состояние для UI.

    У графа два прерывания, и они требуют от клиента разного: `ask_human`
    ждёт ответы на вопросы, `ask_review` — правки оператора поверх готового
    отчёта. Различаются по составу конверта паузы: в первом лежат вопросы, во
    втором отчёт. Один статус на оба означал бы, что фронт шлёт ответы в узел
    правок и получает `ValueError` из недр графа.

    Утечка — не отказ сервера, а факт для оператора: отчёт по такому прогону
    остаётся доступным, поэтому она попадает в статус, а не в исключение.
    """
    if outcome.status == "waiting":
        payload = outcome.payload or {}
        return "awaiting_review" if "report" in payload else "awaiting_answers"
    if outcome.state.get("leaked"):
        return "leaked"
    return "done"


#: Состояния паузы: прогон жив, `finished_at` не проставляется.
_WAITING_STATUSES = frozenset({"awaiting_answers", "awaiting_review"})


def _execute(
    run_id: uuid.UUID,
    thread_id: str,
    *,
    object_name: str,
    options: RunOptions | None,
    answers: dict[str, str] | None,
    edits: dict[str, Any] | None,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> tuple[str, str | None, str | None, str | None]:
    """Один синхронный проход графа: старт либо возобновление.

    Возвращает `(статус, node_hint, текст ошибки, префикс артефактов)` — всё,
    что фоновой задаче нужно записать в `runs`.
    """
    document = _ensure_document(run_id, object_name)
    artifact_dir = _work_dir(run_id) / "artifacts"
    deps = RunDeps(
        llm=llm,
        artifact_dir=artifact_dir,
        pricing=resolve_llm_config().pricing,
    )
    try:
        if options is not None:
            outcome = start_run(
                document,
                options,
                checkpointer_factory=checkpointer_factory,
                deps=deps,
                thread_id=thread_id,
            )
        elif edits is not None:
            outcome = resume_review(
                thread_id,
                edits,
                checkpointer_factory=checkpointer_factory,
                deps=deps,
            )
        else:
            outcome = resume_run(
                thread_id,
                answers or {},
                checkpointer_factory=checkpointer_factory,
                deps=deps,
            )
    except RunFailedError as error:
        return "failed", error.node_hint, str(error), None

    artifacts = artifacts_of(outcome)
    prefix = _upload_artifacts(run_id, artifacts) if artifacts else None
    return _status_of(outcome), None, None, prefix


async def execute_run(
    run_id: uuid.UUID,
    *,
    answers: dict[str, str] | None = None,
    edits: dict[str, Any] | None = None,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> None:
    """Фоновая задача: провести прогон до паузы на вопросах или до конца.

    Своя сессия БД: сессия запроса закрывается вместе с ответом `202`, а
    задача живёт дольше.
    """
    async with async_session_maker() as session:
        run = await session.scalar(select(RunORM).where(RunORM.id == run_id))
        if run is None:
            return
        run.status = "running"
        await session.commit()

        try:
            # Опции нужны только старту: возобновление (ответы или правки)
            # берёт их из состояния треда.
            resuming = answers is not None or edits is not None
            options = (
                None
                if resuming
                else _run_options(RunCreateRequest.model_validate(run.options), run.document_format)
            )
            status, node_hint, error_text, prefix = await run_in_threadpool(
                _execute,
                run.id,
                run.thread_id,
                object_name=run.object_name,
                options=options,
                answers=answers,
                edits=edits,
                llm=llm,
                checkpointer_factory=checkpointer_factory,
            )
        except (OSError, ValueError, UnknownThreadError, AlreadyFinishedError) as exc:
            # Прогон падает целиком, а не оставляет строку в `running`
            # навсегда: оператор обязан увидеть причину в журнале.
            status, node_hint, error_text, prefix = "failed", None, str(exc), None

        if status not in _WAITING_STATUSES:
            # Документ и файлы рендера нужны только до конца прогона: дальше
            # артефакты живут в MinIO, а исходник — в загрузках пользователя.
            shutil.rmtree(_work_dir(run_id), ignore_errors=True)

        run.status = status
        run.node_hint = node_hint
        run.error = error_text
        if prefix is not None:
            run.artifact_prefix = prefix
        run.finished_at = None if status in _WAITING_STATUSES else datetime.now(UTC)
        await session.commit()


async def resume_with_answers(
    run_id: uuid.UUID,
    answers: dict[str, str],
    *,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> None:
    """Возобновить прогон ответами человека — та же фоновая задача."""
    await execute_run(run_id, answers=answers, llm=llm, checkpointer_factory=checkpointer_factory)


async def resume_with_review(
    run_id: uuid.UUID,
    edits: dict[str, Any],
    *,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> None:
    """Применить правки оператора: тот же граф, второй круг plan → … → report."""
    await execute_run(run_id, edits=edits, llm=llm, checkpointer_factory=checkpointer_factory)
