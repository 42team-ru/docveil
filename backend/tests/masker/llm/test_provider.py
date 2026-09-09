from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request

import pytest

from masker.llm import (
    FakeProvider,
    LLMError,
    Message,
    OpenRouterProvider,
    get_provider,
    load_llm_config,
)


def test_fake_provider_is_scriptable_and_deterministic() -> None:
    provider = FakeProvider(["result", "result"])
    messages = [Message("user", "test")]
    assert provider.complete(messages) == "result"
    assert provider.complete(messages) == "result"
    assert provider.calls == 2


_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


def test_fake_provider_call_without_schema_is_unchanged() -> None:
    """Р7-3, п.2: вызов без `schema` ведёт себя как до контракта Р7-3."""
    provider = FakeProvider(['{"unrelated": true}'])
    assert provider.complete([Message("user", "test")]) == '{"unrelated": true}'


def test_fake_provider_accepts_response_matching_schema() -> None:
    provider = FakeProvider(['{"answer": "OK"}'])
    result = provider.complete([Message("user", "test")], schema=_ANSWER_SCHEMA)
    assert result == '{"answer": "OK"}'


def test_fake_provider_rejects_response_not_matching_schema() -> None:
    """Р7-3, п.3: несоответствие схеме — `LLMError`, а не тихий пустой результат."""
    provider = FakeProvider(['{"answer": 42}'])
    with pytest.raises(LLMError, match="schema"):
        provider.complete([Message("user", "test")], schema=_ANSWER_SCHEMA)


def test_fake_provider_rejects_response_missing_required_field() -> None:
    provider = FakeProvider(["{}"])
    with pytest.raises(LLMError, match="schema"):
        provider.complete([Message("user", "test")], schema=_ANSWER_SCHEMA)


def test_fake_provider_rejects_non_json_response_when_schema_given() -> None:
    provider = FakeProvider(["не json вовсе"])
    with pytest.raises(LLMError, match="JSON"):
        provider.complete([Message("user", "test")], schema=_ANSWER_SCHEMA)


def test_openrouter_provider_sends_openai_compatible_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"profiles\\":[]}"}}]}'

    def fake_urlopen(request: object, *, timeout: float) -> Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("masker.llm.openrouter.urlopen", fake_urlopen)
    provider = OpenRouterProvider(
        api_key="secret",
        model="openrouter/auto",
        timeout_seconds=12.5,
        site_url="https://example.test",
        title="test-masker",
    )

    assert provider.complete([Message("system", "rules"), Message("user", "document")]) == (
        '{"profiles":[]}'
    )
    request = captured["request"]
    assert isinstance(request, Request)
    headers = {key.casefold(): value for key, value in request.header_items()}
    assert headers["authorization"] == "Bearer secret"
    assert headers["http-referer"] == "https://example.test"
    assert headers["x-openrouter-title"] == "test-masker"
    assert json.loads(request.data) == {
        "model": "openrouter/auto",
        "messages": [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "document"},
        ],
    }
    assert captured["timeout"] == 12.5


def test_openrouter_sends_schema_as_strict_json_schema_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Р7-3: переданная `schema` уходит в OpenAI-совместимый `response_format`."""
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"answer\\":\\"OK\\"}"}}]}'

    def fake_urlopen(request: object, *, timeout: float) -> Response:
        del timeout
        captured["request"] = request
        return Response()

    monkeypatch.setattr("masker.llm.openrouter.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="secret", model="openrouter/auto")
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }

    result = provider.complete([Message("user", "test")], schema=schema)

    assert result == '{"answer":"OK"}'
    request = captured["request"]
    assert isinstance(request, Request)
    body = json.loads(request.data)
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "triema_masker_response", "strict": True, "schema": schema},
    }


def test_openrouter_without_schema_omits_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Обратная совместимость: без `schema` тело запроса как до Р7-3."""
    captured: dict[str, object] = {}

    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            del exc_type, exc, traceback

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(request: object, *, timeout: float) -> Response:
        del timeout
        captured["request"] = request
        return Response()

    monkeypatch.setattr("masker.llm.openrouter.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="secret", model="openrouter/auto")

    result = provider.complete([Message("user", "test")])

    assert result == "ok"
    request = captured["request"]
    assert isinstance(request, Request)
    body = json.loads(request.data)
    assert "response_format" not in body


def test_openrouter_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("MASKER_LLM", "openrouter")
    monkeypatch.setenv("MASKER_LLM_MODEL", "openrouter/auto")

    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        get_provider()


def test_load_llm_config_keeps_key_in_environment(tmp_path: Path) -> None:
    path = tmp_path / "llm.yaml"
    path.write_text(
        """llm:
  provider: openrouter
  model: openrouter/auto
  api_key_env: TEST_OPENROUTER_KEY
  timeout_seconds: 5
  title: test
""",
        encoding="utf-8",
    )

    config = load_llm_config(path)

    assert config.provider == "openrouter"
    assert config.model == "openrouter/auto"
    assert config.api_key_env == "TEST_OPENROUTER_KEY"
    assert config.timeout_seconds == 5.0


@pytest.mark.e2e
def test_openrouter_live_smoke() -> None:
    """Проверка сети запускается только при явной настройке настоящего провайдера."""
    if os.environ.get("MASKER_LLM") != "openrouter" or not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("нужны MASKER_LLM=openrouter и OPENROUTER_API_KEY")
    provider = get_provider()
    response = provider.complete([Message("user", "Ответь только словом OK")])
    assert response.strip()
