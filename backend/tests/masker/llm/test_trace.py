from __future__ import annotations

import json
from pathlib import Path

import pytest

from masker.llm import FakeProvider, LLMError, Message, TracingProvider, write_trace


class _FailingProvider:
    """Поставщик, который всегда падает — для проверки проброса ошибки."""

    def complete(self, messages: list[Message]) -> str:
        del messages
        raise LLMError("OpenRouter вернул HTTP 500: внутренняя ошибка")


def test_tracing_provider_returns_inner_response_verbatim() -> None:
    inner = FakeProvider(['{"profiles": [], "candidates": []}'])
    tracer = TracingProvider(inner)
    messages = [Message("system", "правила"), Message("user", "документ с ИНН 7701234567")]

    response = tracer.complete(messages)

    assert response == '{"profiles": [], "candidates": []}'
    assert inner.calls == 1


def test_tracing_provider_records_request_and_response_verbatim() -> None:
    inner = FakeProvider(['{"profiles": [], "candidates": []}'])
    tracer = TracingProvider(inner)
    messages = [Message("system", "правила"), Message("user", "документ с ИНН 7701234567")]

    tracer.complete(messages)

    assert len(tracer.calls) == 1
    call = tracer.calls[0]
    assert call.index == 1
    assert call.messages == tuple(messages)
    assert call.response == '{"profiles": [], "candidates": []}'
    assert call.error is None
    assert call.request_chars == len(messages[0].content) + len(messages[1].content)
    assert call.response_chars == len('{"profiles": [], "candidates": []}')
    assert call.duration_ms >= 0.0


def test_tracing_provider_numbers_calls_in_order() -> None:
    inner = FakeProvider(["first", "second"])
    tracer = TracingProvider(inner)

    tracer.complete([Message("user", "1")])
    tracer.complete([Message("user", "2")])

    assert [call.index for call in tracer.calls] == [1, 2]
    assert [call.response for call in tracer.calls] == ["first", "second"]


def test_tracing_provider_reraises_llm_error_and_records_it() -> None:
    tracer = TracingProvider(_FailingProvider())

    with pytest.raises(LLMError, match="HTTP 500"):
        tracer.complete([Message("user", "документ")])

    assert len(tracer.calls) == 1
    call = tracer.calls[0]
    assert call.response is None
    assert call.error is not None
    assert "HTTP 500" in call.error


def test_write_trace_produces_machine_and_human_readable_files(tmp_path: Path) -> None:
    inner = FakeProvider(['{"profiles": [], "candidates": []}'])
    tracer = TracingProvider(inner)
    tracer.complete([Message("system", "правила"), Message("user", "документ с ИНН 7701234567")])

    jsonl_path, markdown_path = write_trace(tmp_path, tracer)

    assert jsonl_path == tmp_path / "llm-trace.jsonl"
    assert markdown_path == tmp_path / "llm-trace.md"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "call"
    assert record["response"] == '{"profiles": [], "candidates": []}'
    assert record["messages"] == [
        {"role": "system", "content": "правила"},
        {"role": "user", "content": "документ с ИНН 7701234567"},
    ]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "документ с ИНН 7701234567" in markdown
    assert '{"profiles": [], "candidates": []}' in markdown


def test_write_trace_files_are_not_world_readable(tmp_path: Path) -> None:
    tracer = TracingProvider(FakeProvider(["ok"]))
    tracer.complete([Message("user", "test")])

    jsonl_path, markdown_path = write_trace(tmp_path, tracer)

    assert oct(jsonl_path.stat().st_mode)[-3:] == "600"
    assert oct(markdown_path.stat().st_mode)[-3:] == "600"
