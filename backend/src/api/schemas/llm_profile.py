"""Схемы настроек LLM-профиля (админ-only)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class LLMPricingIn(BaseModel):
    """Тариф — та же форма, что и `llm.profiles.*.pricing` в `masker.yaml`."""

    prompt_per_1k: float = Field(ge=0)
    completion_per_1k: float = Field(ge=0)
    currency: str = "RUB"
    #: Дата проверки тарифа у поставщика, произвольная строка (как в YAML).
    verified_at: str = ""


class LLMProfileCreate(BaseModel):
    """Тело запроса создания профиля из GUI."""

    name: str
    provider: Literal["fake", "cassette", "openrouter", "gigachat", "ollama"]
    model: str = ""
    #: Имя переменной окружения с ключом/учётными данными — не сам секрет.
    api_key_env: str = "OPENROUTER_API_KEY"
    #: Реальный токен, вставленный прямо в GUI, — альтернатива настройке
    #: переменной окружения на сервере. Хранится в БД, наружу не отдаётся
    #: (см. `LLMProfileOut.has_api_key`). `None` — как раньше, секрет ищется
    #: в окружении процесса по `api_key_env`.
    api_key: str | None = None
    #: Провайдер-специфичные поля (`openrouter`/`gigachat` секции YAML) как есть.
    provider_config: dict[str, Any] = Field(default_factory=dict)
    pricing: LLMPricingIn | None = None


class LLMProfileUpdate(BaseModel):
    """Тело запроса правки своего профиля (`PATCH /admin/llm-profiles/{id}`).

    Имя не меняется: оно же ключ, на который смотрит `llm_active_setting`,
    когда профиль активен, — переименование потребовало бы либо запрета
    редактирования активного профиля, либо синхронной правки указателя;
    проще было не заводить это как задачу, раз имя и так не участвует в
    вызове модели.

    `api_key` отсутствует в теле запроса — сохранённый токен не трогаем
    (форма не обязана перепосылать секрет, который не показывает). Поле
    прислано пустой строкой или `null` — токен очищается. Различие видно
    через `model_fields_set`, а не через сравнение значений."""

    provider: Literal["fake", "cassette", "openrouter", "gigachat", "ollama"]
    model: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key: str | None = None
    provider_config: dict[str, Any] = Field(default_factory=dict)
    pricing: LLMPricingIn | None = None


class LLMProfileOut(BaseModel):
    """Один профиль в списке — встроенный (YAML) или пользовательский (БД)."""

    #: `None` у встроенных профилей — их нельзя ни удалить, ни отредактировать.
    id: uuid.UUID | None
    source: Literal["builtin", "custom"]
    name: str
    provider: str
    model: str
    api_key_env: str
    #: Сохранён ли в БД реальный токен для этого профиля — сам секрет
    #: никогда не возвращается наружу.
    has_api_key: bool
    provider_config: dict[str, Any]
    pricing: LLMPricingIn | None
    is_active: bool
    created_at: datetime | None


class LLMActivateRequest(BaseModel):
    """Тело запроса `POST /admin/llm-profiles/activate`."""

    source: Literal["builtin", "custom"]
    name: str
