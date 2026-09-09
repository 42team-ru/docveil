"""Детерминированный LLM-провайдер с записанными ответами для ворот."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from masker.llm.base import LLMError, Message
from masker.llm.fake import _validate_against_schema


def cassette_key(messages: list[Message]) -> str:
    """Вернуть стабильный ключ ответа для точного набора сообщений.

    В ключ намеренно не входит ``schema``: кассета записывает фактический
    ответ модели на запрос, а схема — контракт вызывающего узла, который
    дополнительно проверяется в ``complete``.
    """
    payload = [{"role": message.role, "content": message.content} for message in messages]
    wire = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


class CassetteProvider:
    """Отвечает строго из JSON-кассет, не обращаясь к сети.

    Каждый файл каталога содержит один объект ``{"key": "<sha256>",
    "response": "<текст модели>"}``. Отсутствующий ключ — ошибка настройки
    кассеты, а не разрешение модели молча ничего не решить.
    """

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._responses = _load_responses(directory)
        self.calls = 0

    def complete(self, messages: list[Message], *, schema: dict[str, Any] | None = None) -> str:
        self.calls += 1
        key = cassette_key(messages)
        try:
            response = self._responses[key]
        except KeyError as error:
            raise LLMError(
                f"в кассете {self._directory} нет ответа для ключа {key}; "
                "запишите ответ живого GigaChat отдельной ручной операцией"
            ) from error
        if schema is not None:
            _validate_against_schema(response, schema)
        return response


def _load_responses(directory: Path) -> dict[str, str]:
    """Прочитать все кассеты и рано сообщить о повреждённой записи."""
    if not directory.is_dir():
        raise LLMError(f"каталог кассет LLM не найден: {directory}")
    responses: dict[str, str] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LLMError(f"не удалось прочитать кассету {path}: {error}") from error
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            raise LLMError(f"кассета {path} не содержит строковый ключ 'key'")
        if not isinstance(item.get("response"), str):
            raise LLMError(f"кассета {path} не содержит строковый ответ 'response'")
        key = item["key"]
        if key in responses:
            raise LLMError(f"дублирующийся ключ {key} в кассете {path}")
        responses[key] = item["response"]
    return responses
