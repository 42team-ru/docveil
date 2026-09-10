"""Детерминированный поставщик для тестов и офлайн-ворот."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from typing import Any

import jsonschema

from masker.llm.base import LLMError, Message


class FakeProvider:
    """Возвращает заранее подготовленные ответы и считает вызовы.

    Не ходит в сеть, поэтому не может попросить настоящую модель соблюсти
    ``schema``. Вместо этого валидирует уже заготовленный ответ локально —
    несоответствие схеме превращается в ``LLMError``, а не в правдоподобный,
    но неверный результат (Р7-3, требование заказчика №6: провайдер, не
    умеющий strict-режим по-настоящему, обязан вести себя предсказуемо).
    """

    def __init__(self, responses: Iterable[str] = ()) -> None:
        self._responses = deque(responses)
        self.calls = 0

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        del messages
        self.calls += 1
        response = (
            self._responses.popleft() if self._responses else '{"profiles": [], "candidates": []}'
        )
        if schema is not None:
            _validate_against_schema(response, schema)
        return response


def _validate_against_schema(response: str, schema: dict[str, Any]) -> None:
    """Проверить, что ``response`` — валидный по ``schema`` JSON.

    Ловит и невалидный JSON, и валидный JSON, не соответствующий схеме:
    оба случая — ошибка контракта, а не пустой результат.
    """
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as error:
        raise LLMError(
            f"FakeProvider: заготовленный ответ не JSON, а схема задана: {error}"
        ) from error
    try:
        jsonschema.validate(instance=parsed, schema=schema)
    except jsonschema.ValidationError as error:
        raise LLMError(
            f"FakeProvider: заготовленный ответ не соответствует schema: {error.message}"
        ) from error
    except jsonschema.SchemaError as error:
        raise LLMError(f"FakeProvider: сама schema некорректна: {error.message}") from error
