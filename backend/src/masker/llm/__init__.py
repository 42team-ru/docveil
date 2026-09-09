"""Поставщики языковых моделей."""

from __future__ import annotations

import os

from masker.llm.base import LLMError, LLMProvider, Message
from masker.llm.config import LLMConfig, load_llm_config
from masker.llm.fake import FakeProvider
from masker.llm.gigachat import DEFAULT_SCOPE as GIGACHAT_DEFAULT_SCOPE
from masker.llm.gigachat import GigaChatProvider
from masker.llm.openrouter import OpenRouterProvider
from masker.llm.trace import BatchTrace, CallTrace, ProfileOutcome, TracingProvider, write_trace

__all__ = [
    "BatchTrace",
    "CallTrace",
    "FakeProvider",
    "GigaChatProvider",
    "LLMConfig",
    "LLMError",
    "LLMProvider",
    "Message",
    "OpenRouterProvider",
    "ProfileOutcome",
    "TracingProvider",
    "get_provider",
    "load_llm_config",
    "write_trace",
]

# Переменная окружения с секретом по умолчанию для каждого провайдера.
# Используется только когда конфигурация строится из окружения
# (`get_provider()` без явного `LLMConfig`) — YAML-конфиг всегда указывает
# `api_key_env` явно через `load_llm_config`.
_DEFAULT_API_KEY_ENV_BY_PROVIDER: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "gigachat": "GIGACHAT_CREDENTIALS",
}


def get_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Создать поставщик из конфигурации или переменных окружения."""
    if config is None:
        provider_name = os.environ.get("MASKER_LLM", "fake").casefold()
        config = LLMConfig(
            provider=provider_name,
            model=os.environ.get("MASKER_LLM_MODEL", ""),
            api_key_env=_DEFAULT_API_KEY_ENV_BY_PROVIDER.get(provider_name, "OPENROUTER_API_KEY"),
        )
    provider = config.provider
    if provider == "fake":
        return FakeProvider()
    if provider == "openrouter":
        api_key = os.environ.get(config.api_key_env, "")
        if not api_key:
            raise LLMError(
                f"не задана переменная окружения {config.api_key_env} с ключом OpenRouter"
            )
        if not config.model:
            raise LLMError("для OpenRouter задайте модель в конфиге или MASKER_LLM_MODEL")
        return OpenRouterProvider(
            api_key=api_key,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            site_url=config.site_url,
            title=config.title,
        )
    if provider == "gigachat":
        credentials = os.environ.get(config.api_key_env, "")
        if not credentials:
            raise LLMError(
                f"не задана переменная окружения {config.api_key_env} с ключом авторизации GigaChat"
            )
        if not config.model:
            raise LLMError("для GigaChat задайте модель в конфиге или MASKER_LLM_MODEL")
        return GigaChatProvider(
            credentials=credentials,
            model=config.model,
            scope=os.environ.get("MASKER_LLM_GIGACHAT_SCOPE", GIGACHAT_DEFAULT_SCOPE),
            timeout_seconds=config.timeout_seconds,
        )
    raise LLMError(f"неизвестный поставщик LLM: {provider!r}")
