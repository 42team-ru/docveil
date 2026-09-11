"""Связка REST-эндпоинтов компиляции с графом `masker.customtypes.graph` (T1.13, шаг 12).

Документ, на котором компилятор считает live preview, приходит из MinIO —
скачивается во временный локальный файл на время `start_compile`; после
`extract_sample_node` сегменты живут в состоянии графа как JSON, и повторный
раунд (`resume_compile`, ответ на вопросы) файл больше не трогает.
"""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

from api.core.config import settings
from api.core.storage import minio_client
from api.schemas.custom_types import (
    AnswerRequest,
    CompiledTypeOut,
    CompileQuestionOut,
    CompileRequest,
    CompileResponse,
    CustomTypeSpecIn,
    FailedTypeOut,
    FailReason,
    PreviewMatchOut,
    PreviewOut,
    PreviewSegmentOut,
)
from masker.customtypes.compiler import available_executors
from masker.customtypes.graph import (
    CheckpointerFactory,
    CompileAlreadyFinishedError,
    CompileDeps,
    CompileRunOutcome,
    UnknownCompileThreadError,
    resume_compile,
    start_compile,
)
from masker.llm import LLMProvider, get_provider
from masker.run import sqlite_checkpointer_factory

__all__ = [
    "CompileAlreadyFinishedError",
    "UnknownCompileThreadError",
    "answer_compile_questions",
    "compile_custom_types",
    "get_compile_checkpointer_factory",
    "get_llm_provider",
]

#: Файл чекпойнтера сессий компиляции — отдельный от `masker.run` (основной
#: граф маскировки использует свой файл под своим `thread_id`).
DEFAULT_STATE_DB = Path("data/custom_types_compile.sqlite")


def get_llm_provider() -> LLMProvider:
    """FastAPI-зависимость: провайдер LLM компилятора.

    Только через `masker.llm.get_provider()` (требование заказчика №6) —
    узлы графа компиляции не знают, какой это провайдер; подмена
    OpenRouter/GigaChat/Fake — вопрос переменных окружения процесса, не кода.
    """
    return get_provider()


def get_compile_checkpointer_factory() -> CheckpointerFactory:
    """FastAPI-зависимость: фабрика чекпойнтера сессий компиляции.

    Переиспользует `masker.run.sqlite_checkpointer_factory` — та же логика
    прав доступа 0600 на файл состояния, что и у основного графа.
    """
    return sqlite_checkpointer_factory(DEFAULT_STATE_DB)


def _download_to_tempfile(object_name: str) -> Path:
    """Скачать объект MinIO во временный файл с тем же расширением.

    Расширение обязано сохраниться: `extract_sample_node` выбирает парсер
    (`ingest_docx`/`ingest_pdf`) по `Path.suffix`.
    """
    suffix = Path(object_name).suffix or ".docx"
    handle, raw_path = tempfile.mkstemp(suffix=suffix)
    os.close(handle)
    tmp_path = Path(raw_path)
    minio_client.fget_object(settings.minio_bucket, object_name, str(tmp_path))
    return tmp_path


def compile_custom_types(
    request: CompileRequest,
    *,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> CompileResponse:
    """Скачать документ, начать сессию компиляции под новым `thread_id`."""
    thread_id = secrets.token_hex(16)
    tmp_path = _download_to_tempfile(request.object_name)
    try:
        outcome = start_compile(
            tmp_path,
            request.descriptions,
            thread_id=thread_id,
            checkpointer_factory=checkpointer_factory,
            deps=CompileDeps(llm=llm),
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return _to_response(outcome)


def answer_compile_questions(
    thread_id: str,
    request: AnswerRequest,
    *,
    llm: LLMProvider,
    checkpointer_factory: CheckpointerFactory,
) -> CompileResponse:
    """Отправить ответы на вопросы приостановленной сессии компиляции.

    Неизвестный или уже завершённый `thread_id` — исключения графа
    (`UnknownCompileThreadError`/`CompileAlreadyFinishedError`), их в 404
    превращает роут, не сервис (симметрично `api.routers.custom_types`).
    """
    outcome = resume_compile(
        thread_id,
        request.answers,
        checkpointer_factory=checkpointer_factory,
        deps=CompileDeps(llm=llm),
    )
    return _to_response(outcome)


def _to_response(outcome: CompileRunOutcome) -> CompileResponse:
    items = outcome.state.get("items", [])
    compiled: list[CompiledTypeOut] = []
    failed: list[FailedTypeOut] = []
    for item in items:
        status = item.get("status")
        if status == "compiled":
            compiled.append(_compiled_out(item))
        elif status == "failed":
            raw_code = str(item.get("code", "cannot_compile"))
            try:
                fail_code = FailReason(raw_code)
            except ValueError:
                fail_code = FailReason.cannot_compile
            failed.append(
                FailedTypeOut(
                    index=int(item["index"]),
                    description=str(item["description"]),
                    reason=str(item.get("reason", "")),
                    code=fail_code,
                )
            )

    questions: list[CompileQuestionOut] = []
    if outcome.status == "waiting" and outcome.payload:
        questions = [
            CompileQuestionOut(
                id=str(question["id"]),
                text=str(question["text"]),
                options=[str(option) for option in question.get("options", [])],
                target=str(question.get("target", "")),
            )
            for question in outcome.payload.get("questions", [])
        ]

    return CompileResponse(
        thread_id=outcome.thread_id,
        status=outcome.status,
        engine_capabilities=sorted(available_executors()),
        compiled=compiled,
        failed=failed,
        questions=questions,
    )


def _compiled_out(item: dict[str, Any]) -> CompiledTypeOut:
    preview_out = _preview_out(item.get("preview"))
    if item.get("outcome_kind") == "use_builtin":
        return CompiledTypeOut(
            outcome="use_builtin",
            type_id=str(item.get("type_id", "")),
            marker_override=item.get("marker_override"),
            preview=preview_out,
        )
    return CompiledTypeOut(
        outcome="compile",
        spec=CustomTypeSpecIn.model_validate(item["spec"]),
        preview=preview_out,
    )


def _preview_out(raw: dict[str, Any] | None) -> PreviewOut | None:
    if raw is None:
        return None
    return PreviewOut(
        segments=[
            PreviewSegmentOut(
                segment_order=int(segment["segment_order"]),
                anchor_label=str(segment["anchor_label"]),
                text=str(segment["text"]),
                matches=[
                    PreviewMatchOut(start=int(m["start"]), end=int(m["end"]), value=str(m["value"]))
                    for m in segment["matches"]
                ],
            )
            for segment in raw["segments"]
        ],
        total_matches=int(raw["total_matches"]),
    )
