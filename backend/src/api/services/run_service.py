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

from fastapi import Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.db import async_session_maker, get_db
from api.core.storage import minio_client
from api.models.run import RunORM
from api.schemas.run import RunCreateRequest
from api.services import llm_profile_service
from api.services.run_events import run_events
from api.services.run_guard import run_guard
from masker.detect.signature_select import select_signature
from masker.graph.nodes import RunDeps
from masker.ingest import SUPPORTED_SUFFIXES as ENGINE_SUFFIXES
from masker.llm import LLMProvider, get_provider
from masker.ocr.select import select_ocr
from masker.run import (
    AlreadyFinishedError,
    CheckpointerFactory,
    RunCancelledError,
    RunFailedError,
    RunInterrupt,
    RunOptions,
    RunOutcome,
    RunTimedOutError,
    UnknownThreadError,
    artifacts_of,
    postgres_checkpointer_factory,
    profile_enabled,
    read_run,
    report_of,
    resume_review,
    resume_run,
    sqlite_checkpointer_factory,
    start_run,
)
from masker.telemetry import LLMPricing

__all__ = [
    "AlreadyFinishedError",
    "RunOutcome",
    "UnknownThreadError",
    "UnsupportedFormatError",
    "artifact_bytes",
    "cancel_run",
    "cleanup_stale_runs",
    "create_run",
    "delete_run",
    "execute_run",
    "get_llm_provider",
    "get_run_checkpointer_factory",
    "list_artifacts",
    "list_runs",
    "read_outcome",
    "regenerate_review",
    "resume_with_answers",
    "resume_with_review",
    "run_events",
    "run_report",
]

#: `--redact-style` веба: то же соответствие, что у CLI (`masker.cli`).
_STYLES_BY_MASK_STYLE: dict[str, tuple[str, ...]] = {
    "marker": ("marker",),
    "blackbox": ("blackbox",),
    "both": ("marker", "blackbox"),
}

#: Единственный источник — слой разбора движка (`masker.ingest`).
SUPPORTED_SUFFIXES = ENGINE_SUFFIXES


class UnsupportedFormatError(Exception):
    """Формат документа движок не обрабатывает — прогон не заводится вовсе."""


async def get_llm_provider(session: AsyncSession = Depends(get_db)) -> LLMProvider:
    """FastAPI-зависимость: провайдер LLM прогона.

    Только через `masker.llm.get_provider()` (требование заказчика №6):
    узлы графа не знают, какой это провайдер. Какой это провайдер — решает
    активный профиль (админка, `llm_profile_service`) поверх YAML-дефолта;
    переменные окружения (`MASKER_LLM*`) сильнее обоих — `get_provider`
    накладывает их сам, эта функция лишь выбирает базовый `LLMConfig`.
    """
    config = await llm_profile_service.resolve_active_llm_config(session)
    return get_provider(config)


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
        # Решение по формату — общее с CLI (`masker.cli`), см. `profile_enabled`.
        profile=profile_enabled(request.profile, document_format),
        unmask_critical=request.unmask_critical,
        # Веб-прогон не останавливается на неоднозначных сущностях: default
        # каждого вопроса — безопасное решение «маскировать».
        interactive=False,
        styles=_STYLES_BY_MASK_STYLE[request.mask_style],
        preview=True,
        review=request.review,
        custom_types=tuple(request.custom_types),
        image_output_format=request.image_output_format,
        highlight_background=request.highlight_background,
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


def artifact_prefix_of(run_id: uuid.UUID, revision: int = 0) -> str:
    """Префикс одного атомарно опубликованного комплекта файлов."""
    return f"runs/{run_id}/revisions/{revision}/"


def artifact_bytes(run_id: uuid.UUID, name: str, artifact_prefix: str | None = None) -> bytes:
    """Скачать артефакт прогона из MinIO."""
    prefix = artifact_prefix or artifact_prefix_of(run_id)
    response = minio_client.get_object(settings.minio_bucket, f"{prefix}{name}")
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


def _upload_artifacts(run_id: uuid.UUID, artifacts: list[dict[str, Any]], revision: int) -> str:
    """Выгрузить полный комплект в новый версионный префикс и вернуть его."""
    prefix = artifact_prefix_of(run_id, revision)
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
    finalize_review: bool,
    artifact_revision: int,
    llm: LLMProvider,
    pricing: LLMPricing | None,
    checkpointer_factory: CheckpointerFactory,
) -> tuple[str, str | None, str | None, str | None]:
    """Один синхронный проход графа: старт либо возобновление.

    Возвращает `(статус, node_hint, текст ошибки, префикс артефактов)` — всё,
    что фоновой задаче нужно записать в `runs`. `llm`/`pricing` резолвит
    вызывающий (`execute_run`) одним и тем же активным профилем — раньше
    `pricing` бралось отдельным вызовом `resolve_llm_config()` без активного
    профиля из БД, и на кастомном профиле стоимость в отчёте не совпадала бы
    с реально использованной моделью.
    """
    run_guard.start(run_id)
    try:
        document = _ensure_document(run_id, object_name)
        artifact_dir = _work_dir(run_id) / "artifacts"

        def observe_progress(node: str, content: dict[str, object]) -> None:
            run_guard.check(run_id)
            run_events.publish(run_id, node, content)

        deps = RunDeps(
            llm=llm,
            artifact_dir=artifact_dir,
            pricing=pricing,
            ocr=select_ocr(),
            signature=select_signature(),
            progress_observer=observe_progress,
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
                    finalize=finalize_review,
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
        except RunInterrupt:
            raise
        except RunFailedError as error:
            return "failed", error.node_hint, str(error), None
    finally:
        run_guard.close(run_id)

    artifacts = artifacts_of(outcome)
    prefix = _upload_artifacts(run_id, artifacts, artifact_revision) if artifacts else None
    return _status_of(outcome), None, None, prefix


async def execute_run(
    run_id: uuid.UUID,
    *,
    answers: dict[str, str] | None = None,
    edits: dict[str, Any] | None = None,
    finalize_review: bool = True,
    artifact_revision: int | None = None,
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
        # Роуты возобновления резервируют статус до постановки фоновой
        # задачи. Для первого запуска это делает сама задача.
        if run.status != "running":
            run.status = "running"
            await session.commit()

        # Тот же активный профиль, что уже выбрал `llm` (собран запросом,
        # который поставил эту фоновую задачу) — своя сессия есть, отдельного
        # резолва без учёта активного профиля из БД здесь не нужно.
        pricing = (await llm_profile_service.resolve_active_llm_config(session)).pricing

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
                finalize_review=finalize_review,
                artifact_revision=(
                    run.artifact_revision if artifact_revision is None else artifact_revision
                ),
                llm=llm,
                pricing=pricing,
                checkpointer_factory=checkpointer_factory,
            )
        except RunCancelledError:
            status, node_hint, error_text, prefix = "cancelled", None, None, None
        except RunTimedOutError as exc:
            status, node_hint, error_text, prefix = "failed", None, str(exc), None
        except (OSError, ValueError, UnknownThreadError, AlreadyFinishedError) as exc:
            # Прогон падает целиком, а не оставляет строку в `running`
            # навсегда: оператор обязан увидеть причину в журнале.
            status, node_hint, error_text, prefix = "failed", None, str(exc), None

        if status not in _WAITING_STATUSES:
            # Документ и файлы рендера нужны только до конца прогона: дальше
            # артефакты живут в MinIO, а исходник — в загрузках пользователя.
            shutil.rmtree(_work_dir(run_id), ignore_errors=True)
            run_events.close(run_id)

        run.status = status
        run.node_hint = node_hint
        run.error = error_text
        if prefix is not None:
            run.artifact_prefix = prefix
            run.artifact_revision = (
                artifact_revision if artifact_revision is not None else run.artifact_revision
            )
        run.finished_at = None if status in _WAITING_STATUSES else datetime.now(UTC)
        await session.commit()


async def cancel_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> RunORM | None:
    """Запросить отмену активного прогона.

    Устанавливает флаг отмены в `run_guard`; фоновый поток поднимет
    `RunCancelledError` на следующей границе узла. Статус меняется там же,
    а не здесь — чтобы не было гонки с фоновой задачей.
    Если прогон уже завершён (не `running`/`queued`) — возвращает `None`.
    """
    run: RunORM | None = await session.scalar(
        select(RunORM).where(RunORM.id == run_id, RunORM.user_id == user_id)
    )
    if run is None:
        return None
    if run.status not in ("running", "queued"):
        return None
    run_guard.cancel(run_id)
    return run


async def delete_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Удалить прогон в любом статусе, остановив его если он активен.

    Возвращает `True` если прогон найден и удалён, `False` если не найден.
    """
    run: RunORM | None = await session.scalar(
        select(RunORM).where(RunORM.id == run_id, RunORM.user_id == user_id)
    )
    if run is None:
        return False

    # Если прогон ещё активен — запросить отмену, чтобы поток завершился.
    if run.status in ("running", "queued"):
        run_guard.cancel(run_id)

    # Очистить рабочий каталог и SSE-брокер.
    shutil.rmtree(_work_dir(run_id), ignore_errors=True)
    run_events.close(run_id)

    await session.delete(run)
    await session.commit()
    return True


async def cleanup_stale_runs(session: AsyncSession | None = None) -> None:
    """Пометить зависшие прогоны как `failed` при старте сервера.

    При перезапуске процесса прогоны в `running`/`queued` остались без
    фоновой задачи — они никогда не завершатся сами. Переводим их в `failed`
    с пояснением, чтобы оператор не ждал вечно.
    """
    error_msg = "Прогон прерван перезапуском сервера"
    now = datetime.now(UTC)

    async def _do_cleanup(s: AsyncSession) -> None:
        await s.execute(
            update(RunORM)
            .where(RunORM.status.in_(["running", "queued"]))
            .values(
                status="failed",
                error=error_msg,
                finished_at=now,
            )
        )
        await s.commit()

    if session is not None:
        await _do_cleanup(session)
    else:
        async with async_session_maker() as s:
            await _do_cleanup(s)


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
    await execute_run(
        run_id,
        edits=edits,
        finalize_review=True,
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )


async def regenerate_review(
    run_id: uuid.UUID,
    edits: dict[str, Any],
    artifact_revision: int,
    *,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> None:
    """Пересобрать результат и вернуться на следующую паузу проверки."""
    await execute_run(
        run_id,
        edits=edits,
        finalize_review=False,
        artifact_revision=artifact_revision,
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )
