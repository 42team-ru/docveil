"""Детерминированный поставщик для тестов и офлайн-ворот."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from masker.llm.base import Message


class FakeProvider:
    """Возвращает заранее подготовленные ответы и считает вызовы."""

    def __init__(self, responses: Iterable[str] = ()) -> None:
        self._responses = deque(responses)
        self.calls = 0

    def complete(self, messages: list[Message]) -> str:
        del messages
        self.calls += 1
        return (
            self._responses.popleft() if self._responses else '{"profiles": [], "candidates": []}'
        )
