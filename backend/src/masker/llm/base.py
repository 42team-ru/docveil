"""Минимальный контракт поставщика LLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class LLMUsage:
    """Фактический расход одного успешного ответа модели.

    ``complete()`` по-прежнему возвращает строку: менять этот контракт ради
    проводки счётчиков означало бы затронуть всех потребителей провайдера.
    Провайдеры с фактическим usage могут дополнительно реализовать
    ``LLMUsageProvider``; обёртка учёта забирает usage из результата одного
    вызова, не записывая изменяемое состояние в экземпляр провайдера.
    """

    prompt_tokens: int
    completion_tokens: int


class LLMError(RuntimeError):
    """Поставщик модели не смог вернуть ответ."""


class LLMProvider(Protocol):
    """Единственная точка входа профилировщика и детектора в LLM.

    ``schema`` — необязательная JSON Schema (draft 2020-12, объект с
    ``type: "object"``, ``properties`` и обязательным ``required``), которой
    должен соответствовать текстовый ответ модели, если распарсить его как
    JSON. Вызов без ``schema`` (``None``, по умолчанию) ведёт себя как
    раньше — узлы графа, которые ещё не передают схему, не меняют поведения.

    Каждый поставщик обязан вести себя предсказуемо, если не может строго
    соблюсти схему, а не молча её игнорировать:

    - ``GigaChatProvider`` и ``OpenRouterProvider`` кладут схему в
      собственный формат `response_format` со strict-режимом запроса;
      модель или API, не поддерживающие структурированный вывод, отвечают
      HTTP-ошибкой (422/400), которая всплывает как ``LLMError`` с текстом
      причины — это не тихая деградация до произвольного текста.
    - ``FakeProvider`` схему не отправляет никуда (сети нет), а проверяет
      локально: ответ, не прошедший ``schema``, — это ``LLMError``, а не
      правдоподобный, но неверный результат.
    """

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str: ...


class LLMUsageProvider(Protocol):
    """Необязательное расширение строкового контракта для обёрток учёта."""

    def complete_with_usage(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None
    ) -> tuple[str, LLMUsage | None]: ...
