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
    provider: Literal["fake", "cassette", "openrouter", "gigachat"]
    model: str = ""
    #: Имя переменной окружения с ключом/учётными данными — не сам секрет.
    api_key_env: str = "OPENROUTER_API_KEY"
    #: Провайдер-специфичные поля (`openrouter`/`gigachat` секции YAML) как есть.
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
    provider_config: dict[str, Any]
    pricing: LLMPricingIn | None
    is_active: bool
    created_at: datetime | None


class LLMActivateRequest(BaseModel):
    """Тело запроса `POST /admin/llm-profiles/activate`."""

    source: Literal["builtin", "custom"]
    name: str
