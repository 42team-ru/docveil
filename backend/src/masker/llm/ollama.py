"""Клиент локального сервера Ollama через его OpenAI-совместимый эндпоинт."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from masker.llm.base import LLMError, LLMUsage, Message

DEFAULT_TEMPERATURE = 0.0


@dataclass(frozen=True, slots=True)
class OllamaProvider:
    """Поставщик Ollama — локальный сервер без ключа по умолчанию.

    Использует ``/v1/chat/completions`` (OpenAI-совместимый режим Ollama),
    а не нативный ``/api/chat`` — так формат ответа и структурированный
    вывод (``response_format.json_schema``) совпадают с `OpenRouterProvider`,
    и не нужен отдельный парсер.
    """

    base_url: str
    model: str
    temperature: float = DEFAULT_TEMPERATURE
    timeout_seconds: float = 60.0

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        return self.complete_with_usage(messages, schema=schema)[0]

    def complete_with_usage(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None
    ) -> tuple[str, LLMUsage | None]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": self.temperature,
        }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "triema_masker_response", "strict": True, "schema": schema},
            }
        request = Request(
            f"{self.base_url.rstrip('/')}/v1/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"Ollama вернул HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise LLMError(
                f"не удалось подключиться к Ollama по адресу {self.base_url}: {error.reason}"
            ) from error
        except OSError as error:
            raise LLMError(f"ошибка соединения с Ollama: {error}") from error
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise LLMError("Ollama вернул ответ без choices[0].message.content") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Ollama вернул пустой текст ответа")
        return content, _usage_from_payload(payload)


def _usage_from_payload(payload: object) -> LLMUsage | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not _token_count(prompt) or not _token_count(completion):
        return None
    assert isinstance(prompt, int)
    assert isinstance(completion, int)
    return LLMUsage(prompt_tokens=prompt, completion_tokens=completion)


def _token_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
