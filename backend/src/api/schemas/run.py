"""Схемы прогона маскирования (веб-слой поверх `masker.run`).

Тонкий фронт над графом: здесь проверяется только форма тела запроса. Отбор
типов, решения по сущностям и сборка отчёта — в узлах графа; ни одна из этих
схем не имеет права заводить свою предметную логику.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Стиль маски в терминах фронта; в `RunOptions.styles` уходит как
#: `marker` → `masked_highlight.*`, `blackbox` → `masked_black.*`
#: (то же соответствие, что у CLI `--redact-style`).
MaskStyle = Literal["marker", "blackbox", "both"]

#: Состояние прогона для UI. `awaiting_answers` — граф стоит на `ask_human`,
#: `awaiting_review` — на `ask_review` (отчёт готов, ждём правок оператора);
#: `leaked` — прогон дошёл до конца, но `validate` нашёл утечку: это данные
#: для оператора, а не ошибка сервера, и отчёт по такому прогону доступен.
RunStatus = Literal[
    "queued",
    "running",
    "awaiting_answers",
    "awaiting_review",
    "done",
    "failed",
    "leaked",
]


class RunDocument(BaseModel):
    """Документ прогона — то, что нужно вьюеру и журналу."""

    name: str
    format: str


class RunCreateRequest(BaseModel):
    """Запуск прогона по уже загруженному в MinIO файлу (`/api/files/upload`)."""

    object_name: str
    #: Типы PII из `masker.model.EntityType`; `None` — все известные типы.
    #: Неизвестное имя типа отвергает сам движок, а не эта схема: реестр
    #: типов живёт единственным местом.
    types: list[str] | None = None
    mask_style: MaskStyle = "marker"
    rules_only: bool = False
    profile: bool = True
    unmask_critical: bool = False
    #: Останавливаться ли после отчёта на правках оператора. По умолчанию да:
    #: экран проверки — часть штатного цикла, а не дополнительная опция.
    review: bool = True
    #: Скомпилированные спеки пользовательских типов
    #: (`/api/custom_types/compile` → `RunOptions.custom_types`).
    custom_types: list[dict[str, Any]] = Field(default_factory=list)
    #: Формат выходного файла при ingest картинки (JPEG/PNG/TIFF):
    #: ``"original"`` — сохранить как исходный, ``"pdf"`` — конвертировать в PDF.
    image_output_format: Literal["original", "pdf"] = "original"


class RunResponse(BaseModel):
    """Состояние одного прогона."""

    id: uuid.UUID
    thread_id: str
    status: RunStatus
    document: RunDocument
    node_hint: str | None = None
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


class RunListItem(BaseModel):
    """Строка журнала обработок (`/history`)."""

    id: uuid.UUID
    status: RunStatus
    document: RunDocument
    created_at: datetime
    finished_at: datetime | None = None


class RunListResponse(BaseModel):
    items: list[RunListItem]
    total: int


class AnswersRequest(BaseModel):
    """Конверт ответов человека — ровно то, что ждёт `masker.graph.questions.parse_answers`."""

    #: Версия конверта ответов. Совпадает с `masker.graph.questions.SCHEMA_VERSION`;
    #: расхождение версий движок отвергает сам (`parse_answers` → `ValueError`),
    #: а клиент получает 422 вместо молча неверно понятых ответов.
    schema_version: Literal[1] = 1
    answers: dict[str, str]


class ManualEntityIn(BaseModel):
    """Значение, которое движок пропустил, а оператор нашёл глазами."""

    type: str
    text: str


class ReviewEdits(BaseModel):
    """Правки оператора: решения по ссылкам, смена типа, добавленные значения."""

    #: `{ref: "mask"|"keep"}` — решение по конкретной ссылке отчёта.
    decisions: dict[str, Literal["mask", "keep"]] = Field(default_factory=dict)
    #: `{ref: type_id}` — оператор поправил тип, маркер пересоберёт движок.
    type_overrides: dict[str, str] = Field(default_factory=dict)
    manual: list[ManualEntityIn] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    """Конверт правок — то, что ждёт `masker.graph.review.parse_review_edits`."""

    #: Версия конверта правок; см. комментарий у `AnswersRequest`.
    schema_version: Literal[1] = 1
    edits: ReviewEdits = Field(default_factory=ReviewEdits)


class ArtifactOut(BaseModel):
    """Артефакт рендера: `preview`, `masked_highlight`, `masked_black`."""

    role: str
    name: str
    redacting: bool
    url: str
