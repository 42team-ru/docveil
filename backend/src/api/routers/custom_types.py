"""Роуты компиляции пользовательских типов (T1.13, шаг 8 — заглушка).

Цель шага — маршруты, авторизация и коды ответов, а не логика компиляции:
`compile_custom_types` — заглушка за тем же интерфейсом, что займёт
настоящий LLM-компилятор (шаг 9) и граф компиляции (шаг 11). Связка роута с
графом — шаг 12 (`api.services.custom_types_service`, файл появится тогда
же — здесь он не нужен).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from api.core.deps import get_current_user
from api.schemas.custom_types import (
    AnswerRequest,
    CompileRequest,
    CompileResponse,
    FailedTypeOut,
)

router = APIRouter(
    prefix="/custom_types", tags=["custom_types"], dependencies=[Depends(get_current_user)]
)


def compile_custom_types(request: CompileRequest) -> CompileResponse:
    """Заглушка компилятора: каждое описание получает `cannot_compile`.

    Настоящая реализация (шаг 9) зовёт LLM через `LLMProvider` и возвращает
    один из четырёх исходов на каждое описание — здесь исход всегда один и
    тот же, `thread_id` каждый раз новый и никогда не приостанавливается
    (`status` всегда `"done"`): у заглушки нет графа, которому есть где
    стоять на паузе.
    """
    thread_id = secrets.token_hex(16)
    return CompileResponse(
        thread_id=thread_id,
        status="done",
        engine_capabilities=[],
        compiled=[],
        failed=[
            FailedTypeOut(
                index=index,
                description=description,
                reason="компилятор пользовательских типов ещё не реализован (T1.13, шаг 9)",
            )
            for index, description in enumerate(request.descriptions)
        ],
        questions=[],
    )


@router.post("/compile", response_model=CompileResponse)
async def compile_types(request: CompileRequest) -> CompileResponse:
    """Скомпилировать пользовательские описания типов по документу."""
    return compile_custom_types(request)


@router.post("/compile/{thread_id}/answers", response_model=CompileResponse)
async def answer_questions(thread_id: str, request: AnswerRequest) -> CompileResponse:
    """Прислать ответы на вопросы приостановленной компиляции.

    Заглушка (шаг 8) никогда не переводит компиляцию в `status: "waiting"`
    (см. `compile_custom_types`), значит ни один `thread_id` не может
    ожидать ответов — любой запрос сюда обязан быть 404, а не молча создавать
    состояние, которого не было.
    """
    del request  # тело используется настоящим графом со связкой шага 12
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, f"неизвестный или уже завершённый thread_id: {thread_id!r}"
    )
