"""Поставщики языковых моделей."""

from __future__ import annotations

import os

from masker.llm.base import LLMError, LLMProvider, Message
from masker.llm.fake import FakeProvider

__all__ = ["FakeProvider", "LLMError", "LLMProvider", "Message", "get_provider"]


def get_provider() -> LLMProvider:
    """Выбрать настроенный поставщик; реализации сети появятся в T3.1."""
    provider = os.environ.get("MASKER_LLM", "fake")
    if provider == "fake":
        return FakeProvider()
    raise LLMError(f"Поставщик {provider!r} появится в T3.1; сейчас доступен только fake")
