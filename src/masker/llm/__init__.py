"""Поставщики языковых моделей."""

from __future__ import annotations

import os

from masker.llm.base import LLMError, LLMProvider, Message
from masker.llm.config import LLMConfig, load_llm_config
from masker.llm.fake import FakeProvider
from masker.llm.openrouter import OpenRouterProvider
from masker.llm.trace import BatchTrace, CallTrace, ProfileOutcome, TracingProvider, write_trace

__all__ = [
    "BatchTrace",
    "CallTrace",
    "FakeProvider",
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


def get_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Создать поставщик из конфигурации или переменных окружения."""
    config = config or LLMConfig(
        provider=os.environ.get("MASKER_LLM", "fake").casefold(),
        model=os.environ.get("MASKER_LLM_MODEL", ""),
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
    raise LLMError(f"неизвестный поставщик LLM: {provider!r}")
