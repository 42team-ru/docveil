"""Синхронный клиент прямого API GigaChat (Сбер).

Транспорт: используем официальный пакет `gigachat` (он уже в зависимостях),
а не собственный HTTP-клиент поверх `urllib`, как для OpenRouter.

Причина — Сбер сам называет совместимость GigaChat с OpenAI API **частичной**:
это отдельный протокол, а не подмена `base_url` у OpenAI-клиента. У него своя
авторизация (OAuth 2.0, заголовок `RqUID`, `scope`, токен живёт 30 минут и
требует кэширования и обновления по истечении, а не переполучения на каждый
вызов), свой набор кодов ошибок (402 — кончились токены, 413 — вход слишком
большой, 422 — неверные параметры, 429 — лимит запросов, каждый требует
своей реакции: одни ретраятся, другие — нет) и `finish_reason=blacklist`
как отдельный исход, который нельзя путать с пустым ответом.

GigaChat работает через сертификаты Минцифры России, которых обычно нет в
стандартном системном хранилище доверенных корневых сертификатов. Без них
любой запрос падает на этапе TLS-рукопожатия:
`httpx.ConnectError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify
failed: self-signed certificate in certificate chain`. Правильное решение —
указать доверенный корневой сертификат явно через `ca_bundle_file`
(параметр `GigaChat.__init__`, путь к уже имеющемуся у пользователя
`.pem`/`.cer`-файлу; переменная окружения `MASKER_LLM_GIGACHAT_CA_BUNDLE`,
см. `.env.example`), а не отключать проверку TLS целиком. Отключение
(`verify_ssl_certs=False`) недоступно как удобный путь по умолчанию — см.
ниже, почему проект вообще не берёт этот пример из документации Сбера;
включить его можно только явно через одноимённый параметр конструктора.

Пакет `gigachat` уже реализует всё перечисленное и проверен библиотекой
кода Сбера: кэширование и автообновление access-токена
(`GigaChatSyncClient._is_token_usable` / `_update_token`), генерацию `RqUID`
на каждый запрос авторизации, ретраи с экспоненциальным backoff
(`gigachat.retry`) по кодам `429/500/502/503/504` — то есть 413 и 422 не
ретраятся по умолчанию, — различение кодов ошибок через иерархию исключений
(`RequestEntityTooLargeError`, `UnprocessableEntityError`, `RateLimitError`,
...), и `verify_ssl_certs=True` по умолчанию. Переписывать это вручную поверх
`urllib` означало бы или тащить `verify_ssl_certs=False` из примеров
документации Сбера, или заново отлаживать нюансы OAuth и ретраев, которые
библиотека уже закрыла. Поэтому `GigaChatProvider` — тонкая адаптация
`gigachat.GigaChat` под протокол `LLMProvider.complete`, а не альтернативный
транспорт.

Мы используем «корневой» chat-эндпоинт клиента (`client.chat(...)`,
известный в документации Сбера как v1: ответ содержит `choices` и
`usage.prompt_tokens`/`usage.completion_tokens`), а не «основной» v2
(`client.chat.create(...)`, ответ содержит `messages` и
`usage.input_tokens`/`usage.output_tokens`) — для протокола
`complete(messages) -> str` это не имеет значения, а первый проще
сопоставляется с уже существующим `OpenRouterProvider` (тоже `choices[0]`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gigachat import GigaChat
from gigachat.exceptions import GigaChatException, ResponseError

from masker.llm.base import LLMError, Message

DEFAULT_SCOPE = "GIGACHAT_API_PERS"


@dataclass(slots=True)
class GigaChatProvider:
    """Поставщик GigaChat; ключ авторизации приходит только из окружения вызывающего процесса.

    Клиент `gigachat.GigaChat` создаётся один раз при первом обращении и
    переиспользуется между вызовами `complete()` — поэтому OAuth-токен
    кэшируется и обновляется библиотекой автоматически по истечении, а не
    запрашивается заново на каждый вызов.
    """

    credentials: str
    model: str
    scope: str = DEFAULT_SCOPE
    timeout_seconds: float = 60.0
    max_retries: int = 3
    retry_backoff_factor: float = 0.5
    verify_ssl_certs: bool = True
    ca_bundle_file: str | None = None
    _client: GigaChat | None = field(default=None, init=False, repr=False, compare=False)

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        """Вернуть текст первого варианта chat completion GigaChat.

        При переданной ``schema`` просит GigaChat о строгом структурированном
        выводе (`response_format.type=json_schema`, `strict: true`) — модель
        или версия API, не поддерживающие этот режим, отвечают HTTP 422,
        который `_describe_response_error` превращает в понятный `LLMError`,
        а не тихо возвращает произвольный текст.
        """
        client = self._get_client()
        payload: dict[str, Any] = {
            "messages": [{"role": item.role, "content": item.content} for item in messages],
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "schema": schema,
                "strict": True,
            }
        try:
            completion = client.chat(payload)
        except ResponseError as error:
            raise LLMError(_describe_response_error(error)) from error
        except GigaChatException as error:
            raise LLMError(f"GigaChat не смог вернуть ответ: {error}") from error
        if not completion.choices:
            raise LLMError("GigaChat вернул ответ без choices")
        choice = completion.choices[0]
        if choice.finish_reason == "blacklist":
            raise LLMError(
                "GigaChat заблокировал ответ по тематическому фильтру (finish_reason=blacklist), "
                "это не пустой результат"
            )
        content = choice.message.content
        if not isinstance(content, str) or not content.strip():
            raise LLMError("GigaChat вернул пустой текст ответа")
        return content

    def _get_client(self) -> GigaChat:
        if self._client is None:
            self._client = GigaChat(
                credentials=self.credentials,
                scope=self.scope,
                model=self.model,
                timeout=self.timeout_seconds,
                verify_ssl_certs=self.verify_ssl_certs,
                ca_bundle_file=self.ca_bundle_file,
                max_retries=self.max_retries,
                retry_backoff_factor=self.retry_backoff_factor,
            )
        return self._client


def _describe_response_error(error: ResponseError) -> str:
    """Перевести код ответа GigaChat в понятное человеку сообщение."""
    status = error.status_code
    if status == 402:
        return f"у GigaChat закончились доступные токены (HTTP 402): {error}"
    if status == 413:
        return f"документ слишком велик для одного запроса к GigaChat (HTTP 413): {error}"
    if status == 422:
        return f"GigaChat отклонил параметры запроса (HTTP 422): {error}"
    if status == 429:
        return f"GigaChat превысил лимит запросов (HTTP 429) после исчерпания повторов: {error}"
    return f"GigaChat вернул HTTP {status}: {error}"
