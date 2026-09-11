"""Поведение утилиты записи кассет Д3 без обращения к живой модели."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _script_module():
    """Загрузить скрипт как модуль: каталог scripts не является пакетом."""
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "pyproject.toml").is_file()
    )
    spec = importlib.util.spec_from_file_location(
        "record_llm_cassettes", root / "scripts" / "record_llm_cassettes.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_record_cassettes_rewrites_same_key_without_duplicate(tmp_path: Path) -> None:
    """Повторная запись одного ответа сохраняет ровно один файл кассеты."""
    script = _script_module()
    responses = {"a" * 64: '{"summary": "Первый ответ"}'}

    script._write_cassettes(tmp_path, responses)
    script._write_cassettes(tmp_path, responses)

    files = list(tmp_path.glob("*.json"))
    assert [path.name for path in files] == ["summary-aaaaaaaaaaaa.json"]
    assert json.loads(files[0].read_text(encoding="utf-8")) == {
        "key": "a" * 64,
        "response": '{"summary": "Первый ответ"}',
    }


def test_recording_provider_reuses_response_without_calling_live_model() -> None:
    """Повторный запрос с тем же ключом не тратит токены у живой модели."""
    script = _script_module()

    class LiveProvider:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, *, schema=None) -> str:  # type: ignore[no-untyped-def]
            self.calls += 1
            return '{"summary": "Новый ответ"}'

    from masker.llm import Message
    from masker.llm.cassette import cassette_key

    messages = [Message("user", "один и тот же запрос")]
    live = LiveProvider()
    recorder = script.RecordingProvider(
        live, {cassette_key(messages): '{"summary": "Записанный ответ"}'}
    )

    response = recorder.complete(messages)

    assert response == '{"summary": "Записанный ответ"}'
    assert live.calls == 0
    assert recorder.recorded == 0
    assert recorder.reused == 1
