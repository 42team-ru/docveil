"""Роуты компиляции пользовательских типов (T1.13, шаг 12 — связка с графом).

Логика компиляции целиком — в `masker.customtypes.graph` (шаг 11) и
`api.services.custom_types_service` (скачивание документа из MinIO, перевод
`CompileRunOutcome` в REST-схему). Роут отвечает только за авторизацию,
внедрение зависимостей (провайдер LLM, чекпойнтер) и коды ответов.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from api.core.deps import get_current_user
from api.schemas.custom_types import AnswerRequest, CompileRequest, CompileResponse
from api.services import custom_types_service
from masker.customtypes.graph import CheckpointerFactory
from masker.llm import LLMProvider

router = APIRouter(
    prefix="/custom_types", tags=["custom_types"], dependencies=[Depends(get_current_user)]
)


@router.post("/compile", response_model=CompileResponse)
async def compile_types(
    request: CompileRequest,
    llm: LLMProvider = Depends(custom_types_service.get_llm_provider),
    checkpointer_factory: CheckpointerFactory = Depends(
        custom_types_service.get_compile_checkpointer_factory
    ),
) -> CompileResponse:
    """Скомпилировать пользовательские описания типов по документу."""
    return await run_in_threadpool(
        custom_types_service.compile_custom_types,
        request,
        llm=llm,
        checkpointer_factory=checkpointer_factory,
    )


@router.post("/compile/{thread_id}/answers", response_model=CompileResponse)
async def answer_questions(
    thread_id: str,
    request: AnswerRequest,
    llm: LLMProvider = Depends(custom_types_service.get_llm_provider),
    checkpointer_factory: CheckpointerFactory = Depends(
        custom_types_service.get_compile_checkpointer_factory
    ),
) -> CompileResponse:
    """Прислать ответы на вопросы приостановленной компиляции.

    Неизвестный или уже завершённый `thread_id` — 404: отвечать сервису
    здесь нечего, а не молча создавать состояние, которого не было.
    """
    try:
        return await run_in_threadpool(
            custom_types_service.answer_compile_questions,
            thread_id,
            request,
            llm=llm,
            checkpointer_factory=checkpointer_factory,
        )
    except (
        custom_types_service.UnknownCompileThreadError,
        custom_types_service.CompileAlreadyFinishedError,
    ) as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
