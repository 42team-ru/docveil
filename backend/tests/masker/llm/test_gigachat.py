"""Тесты провайдера GigaChat: авторизация, ретраи, различение кодов ошибок.

Сеть не используется: транспорт `httpx.Client.request` подменяется фейком,
который эмулирует реальные ответы OAuth- и chat-эндпоинтов GigaChat. Это
проверяет не только наш код, но и то, что конфигурация `GigaChatProvider`
(`max_retries`, `retry_backoff_factor`, `verify_ssl_certs`) действительно
включает ретраи и кэширование токена библиотеки `gigachat`, а не только
теоретически описана в докстринге.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from masker.llm import GigaChatProvider, LLMError, Message, get_provider
from masker.llm.config import LLMConfig
from masker.llm.gigachat import DEFAULT_TEMPERATURE

AUTH_URL_FRAGMENT = "oauth"


def _success_body(text: str) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "created": 1_700_000_000,
        "model": "GigaChat",
        "object": "chat.completion",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@dataclass
class _FakeTransport:
    """Подменяет `httpx.Client.request`, отделяя OAuth-вызовы от chat-вызовов."""

    chat_responses: deque[tuple[int, dict[str, object]]]
    auth_bodies: deque[dict[str, object]] | None = None
    auth_calls: int = 0
    chat_call_headers: list[dict[str, str]] | None = None
    chat_call_bodies: list[str] | None = None

    def __post_init__(self) -> None:
        if self.chat_call_headers is None:
            self.chat_call_headers = []
        if self.chat_call_bodies is None:
            self.chat_call_bodies = []

    def request(self, **kwargs: object) -> httpx.Response:
        method = str(kwargs["method"])
        url = str(kwargs["url"])
        if AUTH_URL_FRAGMENT in url:
            self.auth_calls += 1
            if self.auth_bodies:
                body = self.auth_bodies.popleft()
            else:
                body = {
                    "access_token": f"token-{self.auth_calls}",
                    "expires_at": int((time.time() + 1_800) * 1_000),
                }
            return httpx.Response(200, json=body, request=httpx.Request(method, url))

        headers = dict(kwargs.get("headers") or {})
        assert self.chat_call_headers is not None
        self.chat_call_headers.append(headers)
        assert self.chat_call_bodies is not None
        content = kwargs.get("content")
        self.chat_call_bodies.append(str(content) if content is not None else "")
        if not self.chat_responses:
            raise AssertionError("неожиданный дополнительный вызов chat-эндпоинта GigaChat")
        status, body = self.chat_responses.popleft()
        return httpx.Response(status, json=body, request=httpx.Request(method, url))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ретраи не должны реально ждать секунды в юнит-тестах."""
    import gigachat.retry as giga_retry

    monkeypatch.setattr(giga_retry.time, "sleep", lambda _seconds: None)


def _install_transport(monkeypatch: pytest.MonkeyPatch, transport: _FakeTransport) -> None:
    monkeypatch.setattr(httpx.Client, "request", transport.request)


def _provider(**overrides: object) -> GigaChatProvider:
    defaults: dict[str, object] = {
        "credentials": "dGVzdDp0ZXN0",
        "model": "GigaChat",
        "max_retries": 2,
        "retry_backoff_factor": 0.01,
    }
    defaults.update(overrides)
    return GigaChatProvider(**defaults)  # type: ignore[arg-type]


def test_gigachat_successful_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(chat_responses=deque([(200, _success_body("Ответ модели"))]))
    _install_transport(monkeypatch, transport)

    provider = _provider()
    result = provider.complete([Message("system", "rules"), Message("user", "вопрос")])

    assert result == "Ответ модели"
    assert transport.auth_calls == 1
    assert transport.chat_call_headers is not None
    assert transport.chat_call_headers[0]["Authorization"] == "Bearer token-1"


def test_gigachat_reuses_client_and_caches_token_across_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Второй вызов `complete()` не должен запрашивать новый токен, пока старый жив."""
    transport = _FakeTransport(
        chat_responses=deque([(200, _success_body("первый")), (200, _success_body("второй"))])
    )
    _install_transport(monkeypatch, transport)

    provider = _provider()
    provider.complete([Message("user", "1")])
    provider.complete([Message("user", "2")])

    assert transport.auth_calls == 1
    assert transport.chat_call_headers is not None
    assert (
        transport.chat_call_headers[0]["Authorization"]
        == transport.chat_call_headers[1]["Authorization"]
    )


def test_gigachat_reacquires_token_after_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Просроченный токен переполучается перед следующим вызовом, а не рвёт запрос."""
    now_ms = int(time.time() * 1_000)
    transport = _FakeTransport(
        chat_responses=deque([(200, _success_body("первый")), (200, _success_body("второй"))]),
        auth_bodies=deque(
            [
                {"access_token": "token-stale", "expires_at": now_ms},
                {"access_token": "token-fresh", "expires_at": now_ms + 1_800_000},
            ]
        ),
    )
    _install_transport(monkeypatch, transport)

    provider = _provider()
    provider.complete([Message("user", "1")])
    provider.complete([Message("user", "2")])

    assert transport.auth_calls == 2
    assert transport.chat_call_headers is not None
    assert transport.chat_call_headers[0]["Authorization"] == "Bearer token-stale"
    assert transport.chat_call_headers[1]["Authorization"] == "Bearer token-fresh"


def test_gigachat_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(
        chat_responses=deque(
            [
                (429, {"message": "rate limit"}),
                (200, _success_body("после повтора")),
            ]
        )
    )
    _install_transport(monkeypatch, transport)

    provider = _provider(max_retries=2)
    result = provider.complete([Message("user", "вопрос")])

    assert result == "после повтора"
    assert transport.chat_call_headers is not None
    assert len(transport.chat_call_headers) == 2


def test_gigachat_413_raises_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(chat_responses=deque([(413, {"message": "too large"})]))
    _install_transport(monkeypatch, transport)

    provider = _provider(max_retries=3)

    with pytest.raises(LLMError, match="413"):
        provider.complete([Message("user", "очень длинный документ")])

    assert transport.chat_call_headers is not None
    assert len(transport.chat_call_headers) == 1


def test_gigachat_422_raises_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(chat_responses=deque([(422, {"message": "bad params"})]))
    _install_transport(monkeypatch, transport)

    provider = _provider(max_retries=3)

    with pytest.raises(LLMError, match="422"):
        provider.complete([Message("user", "вопрос")])

    assert transport.chat_call_headers is not None
    assert len(transport.chat_call_headers) == 1


def test_gigachat_402_raises_understandable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(chat_responses=deque([(402, {"message": "no tokens left"})]))
    _install_transport(monkeypatch, transport)

    provider = _provider(max_retries=0)

    with pytest.raises(LLMError, match="402"):
        provider.complete([Message("user", "вопрос")])


def test_gigachat_blacklist_finish_reason_is_not_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _success_body("")
    body["choices"][0]["finish_reason"] = "blacklist"  # type: ignore[index]
    transport = _FakeTransport(chat_responses=deque([(200, body)]))
    _install_transport(monkeypatch, transport)

    provider = _provider()

    with pytest.raises(LLMError, match="blacklist"):
        provider.complete([Message("user", "запрещённая тема")])


def test_gigachat_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GIGACHAT_CREDENTIALS", raising=False)
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")

    with pytest.raises(LLMError, match="GIGACHAT_CREDENTIALS"):
        get_provider()


def test_gigachat_requires_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.delenv("MASKER_LLM_MODEL", raising=False)

    with pytest.raises(LLMError, match="модель"):
        get_provider()


def test_project_yaml_configures_all_gigachat_parameters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "masker.yaml"
    path.write_text(
        """llm:
  provider: gigachat
  model: GigaChat-Pro
  api_key_env: TEST_GIGACHAT_CREDENTIALS
  timeout_seconds: 12
  gigachat:
    scope: GIGACHAT_API_CORP
    temperature: 0.4
    ca_bundle_file: /etc/ssl/certs/trusted-ca.pem
    insecure_skip_tls_verify: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MASKER_CONFIG", str(path))
    monkeypatch.setenv("TEST_GIGACHAT_CREDENTIALS", "test-credentials")

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.model == "GigaChat-Pro"
    assert provider.scope == "GIGACHAT_API_CORP"
    assert provider.temperature == 0.4
    assert provider.timeout_seconds == 12.0
    assert provider.ca_bundle_file == "/etc/ssl/certs/trusted-ca.pem"
    assert provider.verify_ssl_certs is False


def test_get_provider_builds_gigachat_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.model == "GigaChat"
    assert provider.credentials == "dGVzdDp0ZXN0"


def test_get_provider_respects_custom_api_key_env_from_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_GIGACHAT_KEY", "custom-creds")
    config = LLMConfig(provider="gigachat", model="GigaChat-Pro", api_key_env="MY_GIGACHAT_KEY")

    provider = get_provider(config)

    assert isinstance(provider, GigaChatProvider)
    assert provider.credentials == "custom-creds"
    assert provider.model == "GigaChat-Pro"


def test_gigachat_sends_schema_as_strict_json_schema_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Р7-3: переданная `schema` уходит в `response_format` со `strict: true`."""
    transport = _FakeTransport(chat_responses=deque([(200, _success_body('{"a": "x"}'))]))
    _install_transport(monkeypatch, transport)
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
    }

    provider = _provider()
    result = provider.complete([Message("user", "вопрос")], schema=schema)

    assert result == '{"a": "x"}'
    assert transport.chat_call_bodies is not None
    sent = json.loads(transport.chat_call_bodies[0])
    assert sent["response_format"] == {
        "type": "json_schema",
        "schema": schema,
        "strict": True,
    }


def test_gigachat_without_schema_omits_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обратная совместимость: без `schema` запрос выглядит как раньше."""
    transport = _FakeTransport(chat_responses=deque([(200, _success_body("ответ"))]))
    _install_transport(monkeypatch, transport)

    provider = _provider()
    result = provider.complete([Message("user", "вопрос")])

    assert result == "ответ"
    assert transport.chat_call_bodies is not None
    sent = json.loads(transport.chat_call_bodies[0])
    assert "response_format" not in sent


def test_gigachat_sends_default_temperature_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """По умолчанию температура ниже порога строгого контроля Сбера (< 0.001)."""
    transport = _FakeTransport(chat_responses=deque([(200, _success_body("ответ"))]))
    _install_transport(monkeypatch, transport)

    provider = _provider()
    provider.complete([Message("user", "вопрос")])

    assert transport.chat_call_bodies is not None
    sent = json.loads(transport.chat_call_bodies[0])
    assert sent["temperature"] == DEFAULT_TEMPERATURE
    assert DEFAULT_TEMPERATURE < 0.001


def test_gigachat_forwards_custom_temperature_in_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _FakeTransport(chat_responses=deque([(200, _success_body("ответ"))]))
    _install_transport(monkeypatch, transport)

    provider = _provider(temperature=0.9)
    provider.complete([Message("user", "вопрос")])

    assert transport.chat_call_bodies is not None
    sent = json.loads(transport.chat_call_bodies[0])
    assert sent["temperature"] == 0.9


def test_get_provider_builds_gigachat_with_default_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.delenv("MASKER_LLM_GIGACHAT_TEMPERATURE", raising=False)

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.temperature == DEFAULT_TEMPERATURE


def test_get_provider_reads_gigachat_temperature_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.setenv("MASKER_LLM_GIGACHAT_TEMPERATURE", "0.3")

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.temperature == 0.3


def test_get_provider_rejects_non_numeric_gigachat_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.setenv("MASKER_LLM_GIGACHAT_TEMPERATURE", "много")

    with pytest.raises(LLMError, match="MASKER_LLM_GIGACHAT_TEMPERATURE"):
        get_provider()


def test_masker_llm_fake_still_works_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASKER_LLM", "fake")
    provider = get_provider()
    assert provider.complete([Message("user", "test")])


def test_gigachat_provider_defaults_ca_bundle_file_to_none() -> None:
    """Без явного указания сертификата поведение не меняется (verify_ssl_certs=True)."""
    provider = _provider()
    assert provider.ca_bundle_file is None
    assert provider.verify_ssl_certs is True


def test_gigachat_forwards_ca_bundle_file_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Р9: путь к доверенному корневому сертификату (Минцифры) доходит до `gigachat.GigaChat`.

    Без этого параметра запрос падает на машинах без сертификатов Минцифры
    в системном хранилище: `SSL: CERTIFICATE_VERIFY_FAILED`. Проверяем, что
    провайдер прокидывает `ca_bundle_file` в клиент, не проверяя реальную сеть.
    """
    captured: dict[str, object] = {}

    class _SpyGigaChat:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def chat(self, payload: object) -> None:  # pragma: no cover - не должен вызываться
            raise AssertionError("chat не должен вызываться в этом тесте")

    monkeypatch.setattr("masker.llm.gigachat.GigaChat", _SpyGigaChat)

    provider = _provider(ca_bundle_file="/etc/ssl/certs/russian_trusted_root_ca.cer")
    provider._get_client()

    assert captured["ca_bundle_file"] == "/etc/ssl/certs/russian_trusted_root_ca.cer"
    assert captured["verify_ssl_certs"] is True


def test_get_provider_reads_gigachat_ca_bundle_file_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.setenv(
        "MASKER_LLM_GIGACHAT_CA_BUNDLE", "/etc/ssl/certs/russian_trusted_root_ca.cer"
    )

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.ca_bundle_file == "/etc/ssl/certs/russian_trusted_root_ca.cer"


def test_get_provider_without_ca_bundle_env_leaves_it_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.delenv("MASKER_LLM_GIGACHAT_CA_BUNDLE", raising=False)

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.ca_bundle_file is None


def test_get_provider_gigachat_verify_ssl_certs_defaults_to_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Небезопасный режим не включается сам по себе без явной переменной."""
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.delenv("MASKER_LLM_GIGACHAT_INSECURE_SKIP_TLS_VERIFY", raising=False)

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.verify_ssl_certs is True


def test_get_provider_gigachat_insecure_flag_disables_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Р9: отключение проверки TLS — только осознанным явным флагом, не по умолчанию."""
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "dGVzdDp0ZXN0")
    monkeypatch.setenv("MASKER_LLM", "gigachat")
    monkeypatch.setenv("MASKER_LLM_MODEL", "GigaChat")
    monkeypatch.setenv("MASKER_LLM_GIGACHAT_INSECURE_SKIP_TLS_VERIFY", "1")

    provider = get_provider()

    assert isinstance(provider, GigaChatProvider)
    assert provider.verify_ssl_certs is False


@pytest.mark.e2e
def test_gigachat_live_smoke() -> None:
    """Проверка сети запускается только при явной настройке настоящего GigaChat."""
    if os.environ.get("MASKER_LLM") != "gigachat" or not os.environ.get("GIGACHAT_CREDENTIALS"):
        pytest.skip("нужны MASKER_LLM=gigachat и GIGACHAT_CREDENTIALS")
    provider = get_provider()
    response = provider.complete([Message("user", "Ответь только словом OK")])
    assert response.strip()


@pytest.mark.e2e
def test_gigachat_live_strict_schema_returns_schema_valid_json() -> None:
    """Р7-3, п.4: живой GigaChat со `strict: true` возвращает валидный по схеме JSON."""
    if os.environ.get("MASKER_LLM") != "gigachat" or not os.environ.get("GIGACHAT_CREDENTIALS"):
        pytest.skip("нужны MASKER_LLM=gigachat и GIGACHAT_CREDENTIALS")
    import jsonschema

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    provider = get_provider()
    response = provider.complete(
        [Message("user", 'Ответь JSON-объектом {"answer": "OK"} и ничем больше')],
        schema=schema,
    )
    parsed = json.loads(response)
    jsonschema.validate(instance=parsed, schema=schema)
