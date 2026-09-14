"""Схемы пользовательских типов сущностей (T1.13, шаг 7).

Тонкий фронт над `masker.typeconfig.load_type_config`: здесь проверяется
только форма тела запроса (обязательные поля, `detect.kind` из известного
набора, типы значений). AST-валидатор регулярок (защита от катастрофического
бэктрекинга, запрет обратных ссылок и т.п.) не дублируется — он живёт
единственным местом в `load_type_config`, и туда уходит уже провалидированное
Pydantic тело (`CustomTypeSpecIn.model_dump()` — валидный элемент списка
``types`` для ``load_type_config({"version": 1, "types": [...]})``).

``schema_version`` у `CustomTypeSpecIn` — версия формата самой спеки
(design notes T1.13, раздел 2.2: «CustomTypeSpec — plain dataclass с
schema_version», задел на будущее хранение пресетов), не то же самое, что
поле ``version`` тела ``load_type_config`` — они меняются независимо.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

#: Версия формата одной пользовательской спеки. Поднимается руками при
#: несовместимой смене состава полей — старый клиент получит 422, а не
#: молча неверно интерпретированную спеку.
CUSTOM_TYPE_SCHEMA_VERSION: Literal[1] = 1

#: Версия конверта ответа на вопросы компилятора (симметрично
#: ``masker.graph.questions.SCHEMA_VERSION`` — тот же приём для другого
#: прерывания графа, см. план T1.13, шаг 11).
ANSWER_SCHEMA_VERSION: Literal[1] = 1


class LiteralsDetectIn(BaseModel):
    """Точный список значений (executor ``literals``, `typeconfig.py`)."""

    kind: Literal["literals"]
    values: list[str] = Field(min_length=1)
    match: Literal["whole_word", "substring"] = "whole_word"
    ignorecase: bool = False


class RegexDetectIn(BaseModel):
    """Регулярка, опционально с якорными словами контекста (``regex``/``regex_context``).

    Имя ``regex_context`` — только для промпта LLM-компилятора (план,
    раздел «Отвергнутые альтернативы»): на схеме это тот же ``kind="regex"``
    с непустым ``context``.
    """

    kind: Literal["regex"]
    pattern: str = Field(min_length=1)
    context: list[str] = Field(default_factory=list)
    ignorecase: bool = False


class GlinerLabelDetectIn(BaseModel):
    """Именованная семантическая категория (executor ``gliner_label``, T1.13.1)."""

    kind: Literal["gliner_label"]
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    threshold: float = Field(default=0.3, ge=0.0, le=1.0)


class GlinerStructureDetectIn(BaseModel):
    """Роль поверх структуры документа (executor ``gliner_structure``, T1.13.1)."""

    kind: Literal["gliner_structure"]
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    structure: str = Field(min_length=1)
    field: str = Field(min_length=1)
    threshold: float = Field(default=0.3, ge=0.0, le=1.0)


#: Дискриминированный по ``detect.kind`` union — неизвестный ``kind`` даёт
#: 422 с ошибкой на пути ``detect`` (FastAPI/Pydantic сообщают
#: `union_tag_invalid`, тело содержит полученное значение ``kind``).
DetectIn = Annotated[
    LiteralsDetectIn | RegexDetectIn | GlinerLabelDetectIn | GlinerStructureDetectIn,
    Field(discriminator="kind"),
]


class CustomTypeSpecIn(BaseModel):
    """Пользовательский тип из тела REST-запроса — вход `load_type_config`.

    Полей меньше, чем проверяет `load_type_config` (например, формат
    `id` и плейсхолдер в `marker` здесь не проверяются намеренно —
    «тонкий фронт», раздел докстринга модуля).
    """

    schema_version: Literal[1] = CUSTOM_TYPE_SCHEMA_VERSION
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    marker: str = Field(min_length=1)
    critical: bool = False
    detect: DetectIn


class PreviewMatchOut(BaseModel):
    """Одно совпадение внутри окна ``PreviewSegmentOut.text``."""

    start: int
    end: int
    value: str


class PreviewSegmentOut(BaseModel):
    """Сегмент документа с окном ±120 символов вокруг совпадения (план, шаг 7).

    Смещения ``matches`` локальны в этом ``text``, а не в документе целиком
    — фронту не нужно пересчитывать координаты (design notes, вопрос 2).
    """

    segment_order: int
    anchor_label: str
    text: str
    matches: list[PreviewMatchOut] = Field(default_factory=list)


class PreviewOut(BaseModel):
    """Итог live preview (T1.13, шаг 10): до трёх сегментов, реально исполненных."""

    segments: list[PreviewSegmentOut] = Field(default_factory=list)
    total_matches: int = 0


class CompiledTypeOut(BaseModel):
    """Один успешно обработанный элемент `CompileRequest.descriptions`.

    ``outcome == "compile"``: заполнен ``spec`` — готовая спека. ``outcome
    == "use_builtin"``: спеки нет (тип уже покрыт встроенным детектором,
    компилировать нечего) — заполнены ``type_id`` и, если пользователь
    попросил другую метку маркера, ``marker_override`` (design notes T1.13,
    раздел 2.6). Ровно один из ``spec``/``type_id`` осмыслен для данного
    ``outcome`` — второй остаётся ``None``.
    """

    outcome: Literal["compile", "use_builtin"]
    spec: CustomTypeSpecIn | None = None
    type_id: str | None = None
    marker_override: str | None = None
    preview: PreviewOut | None = None


class FailReason(StrEnum):
    """Машиночитаемый код причины отказа компилятора."""

    empty_description = "empty_description"
    too_short = "too_short"
    too_long = "too_long"
    llm_unavailable = "llm_unavailable"
    invalid_regex = "invalid_regex"
    redos_pattern = "redos_pattern"
    regex_too_long = "regex_too_long"
    empty_match = "empty_match"
    cannot_compile = "cannot_compile"
    ask_rounds_exhausted = "ask_rounds_exhausted"
    preview_error = "preview_error"


class FailedTypeOut(BaseModel):
    """Элемент `CompileRequest.descriptions`, который компилятор не осилил
    (после ретрая на невалидном JSON/регулярке или после `MAX_ASK_ROUNDS`)."""

    index: int
    description: str
    reason: str
    code: FailReason = FailReason.cannot_compile


class CompileQuestionOut(BaseModel):
    """Один вопрос уточнения от компилятора — конверт `ask_types` (T1.13, шаг 11)."""

    id: str
    text: str
    options: list[str] = Field(default_factory=list)
    target: str


class CompileRequest(BaseModel):
    """Тело `POST /custom_types/compile`.

    ``object_name`` — файл в MinIO (тот же идентификатор, что возвращает
    `POST /files/upload`, `api.schemas.file.FileUploadResponse`): live
    preview (шаг 10) исполняет executor'ы по настоящим сегментам этого
    документа, а не по синтетике. ``descriptions`` — по одному пользовательскому
    типу словами на элемент списка; частичный успех (design notes, вопрос 3)
    разбирает их независимо друг от друга.
    """

    object_name: str = Field(min_length=1)
    descriptions: list[str] = Field(min_length=1)

    @field_validator("descriptions", mode="before")
    @classmethod
    def _validate_descriptions(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        cleaned = []
        for item in value:
            if not isinstance(item, str):
                cleaned.append(item)
                continue
            text = item.strip()
            if not text:
                raise ValueError("описание не может быть пустым или состоять только из пробелов")
            if len(text) < 8:
                raise ValueError(f"описание слишком короткое ({len(text)} символов), минимум 8")
            if len(text) > 1000:
                raise ValueError(f"описание слишком длинное ({len(text)} символов), максимум 1000")
            cleaned.append(text)
        return cleaned


class CompileResponse(BaseModel):
    """Ответ `POST /custom_types/compile` и `.../compile/{thread_id}/answers`."""

    thread_id: str
    status: Literal["done", "waiting"]
    engine_capabilities: list[str] = Field(default_factory=list)
    compiled: list[CompiledTypeOut] = Field(default_factory=list)
    failed: list[FailedTypeOut] = Field(default_factory=list)
    questions: list[CompileQuestionOut] = Field(default_factory=list)


class AnswerRequest(BaseModel):
    """Тело `POST /custom_types/compile/{thread_id}/answers` — ответы на `questions`.

    Конверт с версией, а не голый словарь — по той же причине, что и у
    основного графа (`masker.run.resume_run`): пустой `answers` не должен
    молча трактоваться как «нет значения» на стороне LangGraph.
    """

    schema_version: Literal[1] = ANSWER_SCHEMA_VERSION
    answers: dict[str, str] = Field(default_factory=dict)
