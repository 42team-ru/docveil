from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from masker.llm import CassetteProvider, LLMError, Message, get_provider
from masker.llm.cassette import cassette_key

FIXTURES = Path(__file__).parents[3] / "fixtures" / "llm" / "roles"
_MESSAGES = [Message("system", "cassette-test"), Message("user", "source")]
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"profiles": {"type": "array"}},
    "required": ["profiles"],
    "additionalProperties": False,
}


def test_cassette_returns_recorded_response_by_message_hash() -> None:
    provider = CassetteProvider(FIXTURES)

    assert provider.complete(_MESSAGES, schema=_SCHEMA) == '{"profiles": []}'
    assert provider.calls == 1


def test_cassette_missing_key_is_explicit_error() -> None:
    provider = CassetteProvider(FIXTURES)

    with pytest.raises(LLMError, match="нет ответа для ключа"):
        provider.complete([Message("user", "absent")])


def test_cassette_validates_recorded_response_against_schema(tmp_path: Path) -> None:
    messages = [Message("user", "schema")]
    (tmp_path / "invalid.json").write_text(
        json.dumps({"key": cassette_key(messages), "response": '{"profiles": "not-array"}'}),
        encoding="utf-8",
    )

    with pytest.raises(LLMError, match="schema"):
        CassetteProvider(tmp_path).complete(messages, schema=_SCHEMA)


def test_get_provider_registers_cassette(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASKER_LLM", "cassette")
    monkeypatch.setenv("MASKER_LLM_CASSETTE_DIR", str(FIXTURES))

    assert isinstance(get_provider(), CassetteProvider)
