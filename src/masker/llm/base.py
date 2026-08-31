"""Минимальный контракт поставщика LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


class LLMError(RuntimeError):
    """Поставщик модели не смог вернуть ответ."""


class LLMProvider(Protocol):
    """Единственная точка входа профилировщика в LLM."""

    def complete(self, messages: list[Message]) -> str: ...
