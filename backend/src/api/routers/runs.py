"""Роуты прогона маскирования — тонкая обёртка над графом `masker.run`.

Роут отвечает за авторизацию, внедрение зависимостей (провайдер LLM,
чекпойнтер), коды ответов и перевод исключений `masker.run` в HTTP. Ни отбора
типов, ни решений по сущностям, ни сборки отчёта здесь нет: всё это — узлы
графа, а роут только сериализует их вход и выход.

Прогон асинхронный: `POST /runs` заводит строку и отдаёт `202`, граф крутится
фоновой задачей, фронт опрашивает `GET /runs/{id}`. Синхронный ответ упёрся бы
в таймаут прокси на прогоне с LLM и не пережил бы перезагрузку вкладки, тогда
как опрос читает состояние из чекпойнтера LangGraph.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.core.db import get_db
from api.core.deps import get_current_user
from api.models.run import RunORM
from api.models.user import UserORM
from api.schemas.run import (
    AnswersRequest,
    ArtifactOut,
    ReviewRequest,
    RunCreateRequest,
    RunDocument,
    RunListItem,
    RunListResponse,
    RunResponse,
    RunStatus,
)
from api.services import run_service
from masker.llm import LLMProvider
from masker.run import CheckpointerFactory

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(get_current_user)])

#: MIME-типы артефактов по расширению — иначе браузер получит `octet-stream`
#: и не покажет документ во вьюере.
_MEDIA_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}


def _run_response(run: RunORM) -> RunResponse:
    return RunResponse(
        id=run.id,
        thread_id=run.thread_id,
        status=run.status,  # type: ignore[arg-type]
        document=RunDocument(name=run.document_name, format=run.document_format),
        node_hint=run.node_hint,
        error=run.error,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


async def _require_run(session: AsyncSession, user: UserORM, run_id: uuid.UUID) -> RunORM:
    run = await run_service.get_run(session, user.id, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"прогон {run_id} не найден")
    return run


@router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    request: RunCreateRequest,
    background: BackgroundTasks,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(run_service.get_llm_provider),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> RunResponse:
    """Запустить прогон по загруженному файлу; граф крутится фоном."""
    try:
        run = await run_service.create_run(session, user.id, request)
    except run_service.UnsupportedFormatError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error

    background.add_task(
        run_service.execute_run,
        run.id,
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )
    return _run_response(run)


@router.get("", response_model=RunListResponse)
async def list_runs(
    query: str | None = Query(default=None),
    run_status: RunStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RunListResponse:
    """Журнал обработок текущего пользователя."""
    runs, total = await run_service.list_runs(
        session, user.id, query=query, status=run_status, limit=limit, offset=offset
    )
    return RunListResponse(
        items=[
            RunListItem(
                id=run.id,
                status=run.status,  # type: ignore[arg-type]
                document=RunDocument(name=run.document_name, format=run.document_format),
                created_at=run.created_at,
                finished_at=run.finished_at,
            )
            for run in runs
        ],
        total=total,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RunResponse:
    """Состояние прогона — то, что опрашивает фронт."""
    return _run_response(await _require_run(session, user, run_id))


@router.get("/{run_id}/questions")
async def get_questions(
    run_id: uuid.UUID,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> dict[str, object]:
    """Конверт вопросов приостановленного прогона (`ask_human`).

    404 — прогон ещё не дошёл до паузы или уже завершён: вопросов нет, и
    выдумывать пустой конверт вместо честного «нечего спрашивать» нельзя.
    """
    run = await _require_run(session, user, run_id)
    outcome = await _read_outcome(run, checkpointer_factory)
    payload = outcome.payload or {}
    if outcome.status != "waiting" or "questions" not in payload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"прогон {run_id} не ждёт ответов")
    return dict(payload)


@router.post("/{run_id}/answers", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_answers(
    run_id: uuid.UUID,
    request: AnswersRequest,
    background: BackgroundTasks,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(run_service.get_llm_provider),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> RunResponse:
    """Прислать ответы человека и продолжить прогон фоном."""
    run = await _require_run(session, user, run_id)
    if run.status != "awaiting_answers":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"прогон {run_id} в состоянии {run.status!r}, ответы сейчас не принимаются",
        )

    background.add_task(
        run_service.resume_with_answers,
        run.id,
        request.answers,
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )
    return _run_response(run)


@router.post("/{run_id}/review", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def post_review(
    run_id: uuid.UUID,
    request: ReviewRequest,
    background: BackgroundTasks,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    llm: LLMProvider = Depends(run_service.get_llm_provider),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> RunResponse:
    """Утвердить документ с правками оператора.

    Правки не применяются здесь: они уходят вторым прерыванием в граф, и
    документ пересобирается штатным путём `plan → … → report`. Поэтому маркеры
    остаются согласованными, критичные типы — под защитой, а результат заново
    проверяется на утечки.
    """
    run = await _require_run(session, user, run_id)
    if run.status != "awaiting_review":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"прогон {run_id} в состоянии {run.status!r}, правки сейчас не принимаются",
        )

    background.add_task(
        run_service.resume_with_review,
        run.id,
        request.edits.model_dump(mode="json"),
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )
    return _run_response(run)


@router.get("/{run_id}/review")
async def get_review_payload(
    run_id: uuid.UUID,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> dict[str, object]:
    """Конверт паузы раунда правок: отчёт, который правит оператор."""
    run = await _require_run(session, user, run_id)
    outcome = await _read_outcome(run, checkpointer_factory)
    payload = outcome.payload or {}
    if outcome.status != "waiting" or "report" not in payload:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"прогон {run_id} не ждёт правок")
    return dict(payload)


@router.get("/{run_id}/report")
async def get_report(
    run_id: uuid.UUID,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> dict[str, object]:
    """`report.json` прогона — ровно то, что собрал узел `report`."""
    run = await _require_run(session, user, run_id)
    outcome = await _read_outcome(run, checkpointer_factory)
    report = dict(outcome.state.get("report", {}))
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"у прогона {run_id} ещё нет отчёта")
    return report


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
async def get_artifacts(
    run_id: uuid.UUID,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> list[ArtifactOut]:
    """Список файлов рендера со ссылками на скачивание."""
    run = await _require_run(session, user, run_id)
    outcome = await _read_outcome(run, checkpointer_factory)
    return [
        ArtifactOut(
            role=str(artifact["role"]),
            name=str(artifact["name"]),
            redacting=bool(artifact["redacting"]),
            url=f"/api/runs/{run_id}/artifacts/{artifact['role']}",
        )
        for artifact in outcome.state.get("artifacts", [])
    ]


@router.get("/{run_id}/artifacts/{role}")
async def download_artifact(
    run_id: uuid.UUID,
    role: str,
    user: UserORM = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    checkpointer_factory: CheckpointerFactory = Depends(run_service.get_run_checkpointer_factory),
) -> Response:
    """Отдать файл рендера — им фронт кормит вьюер и кнопку «Скачать»."""
    run = await _require_run(session, user, run_id)
    outcome = await _read_outcome(run, checkpointer_factory)
    names = {str(item["role"]): str(item["name"]) for item in outcome.state.get("artifacts", [])}
    if role not in names:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"у прогона {run_id} нет артефакта {role!r}")

    name = names[role]
    payload = await run_in_threadpool(run_service.artifact_bytes, run.id, name)
    suffix = name[name.rfind(".") :] if "." in name else ""
    return Response(
        content=payload,
        media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"),
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


async def _read_outcome(
    run: RunORM, checkpointer_factory: CheckpointerFactory
) -> run_service.RunOutcome:
    """Состояние графа по треду прогона; неизвестный тред — 404, а не 500.

    Тред неизвестен, пока фоновая задача не дошла до первого чекпойнта: для
    только что заведённого прогона это штатное «ещё нечего показывать».
    """
    try:
        return await run_in_threadpool(
            run_service.read_outcome, run.thread_id, checkpointer_factory=checkpointer_factory
        )
    except run_service.UnknownThreadError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"прогон {run.id} ещё не начался") from error
