"""Синхронный клиент совместимого с OpenAI API OpenRouter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from masker.llm.base import LLMError, LLMUsage, Message

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

#: Имя строгой JSON-схемы в запросе к OpenRouter (OpenAI-совместимый формат
#: `response_format.json_schema.name`): API требует непустое имя, а не сам
#: контракт `LLMProvider`, поэтому оно константа, а не параметр вызывающего.
SCHEMA_NAME = "triema_masker_response"

# OpenAI-совместимый параметр `temperature` (диапазон 0..2, 0 — минимум
# шкалы, максимально предсказуемый вывод). В отличие от GigaChat, где
# документация Сбера называет отдельный порог строгого контроля (< 0.001),
# у OpenAI-совместимого API нижняя граница диапазона сама по себе и есть
# «детерминированный» режим, поэтому берём именно 0, а не значение чуть
# выше нуля. Используется для тех же ролей, что и GigaChat (роль стороны
# договора, верификатор Р7) — это извлечение фактов, где нужна
# повторяемость, а не разнообразие.
DEFAULT_TEMPERATURE = 0.0


@dataclass(frozen=True, slots=True)
class OpenRouterProvider:
    """Поставщик OpenRouter; ключ приходит только из окружения вызывающего процесса."""

    api_key: str
    model: str
    temperature: float = DEFAULT_TEMPERATURE
    timeout_seconds: float = 60.0
    site_url: str = ""
    title: str = "triema-masker"
    #: Кому из хостеров модели отдать запрос (`novita`, `deepseek`, …).
    #: Пусто — маршрутизацию выбирает OpenRouter сам. Закреплять хостера
    #: осмысленно ради воспроизводимости замера: у разных хостеров одной
    #: модели разные задержка, пропускная способность и, что важнее для
    #: наших строгих схем, разная доля ошибок структурированного ответа.
    provider_order: tuple[str, ...] = ()

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        """Вернуть текст; usage доступен обёрткам через ``complete_with_usage``."""
        return self.complete_with_usage(messages, schema=schema)[0]

    def complete_with_usage(
        self, messages: list[Message], *, schema: dict[str, Any] | None = None
    ) -> tuple[str, LLMUsage | None]:
        """Вернуть текст первого варианта chat completion.

        При переданной ``schema`` просит строгий структурированный вывод в
        OpenAI-совместимом формате (`response_format.json_schema.strict`).
        Часть моделей за OpenRouter этот режим не поддерживает — тогда
        API отвечает HTTP-ошибкой, которую мы поднимаем как `LLMError` с
        телом ответа, а не проглатываем и не возвращаем произвольный текст.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": self.temperature,
        }
        if self.provider_order:
            # `allow_fallbacks: False` — иначе OpenRouter молча уйдёт к
            # другому хостеру, и замер будет приписан не тому, кого мерили.
            body["provider"] = {
                "order": list(self.provider_order),
                "allow_fallbacks": False,
            }
        if schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "strict": True,
                    "schema": schema,
                },
            }
        request = Request(
            OPENROUTER_CHAT_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"OpenRouter вернул HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise LLMError(f"не удалось подключиться к OpenRouter: {error.reason}") from error
        except OSError as error:
            raise LLMError(f"ошибка соединения с OpenRouter: {error}") from error
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise LLMError("OpenRouter вернул ответ без choices[0].message.content") from error
        if not isinstance(content, str) or not content.strip():
            raise LLMError("OpenRouter вернул пустой текст ответа")
        return content, _usage_from_payload(payload)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": self.title,
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        return headers


def _usage_from_payload(payload: object) -> LLMUsage | None:
    """Забрать OpenAI-совместимый ``usage`` без оценки токенов по тексту."""
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
