"""Общий YAML-конфиг: необязательность и безопасная форма."""

from __future__ import annotations

import pytest

from masker.config import load_project_config


def test_missing_project_yaml_returns_empty_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отсутствующий YAML не мешает голому CLI и библиотеке masker."""
    monkeypatch.delenv("MASKER_CONFIG", raising=False)
    monkeypatch.setattr("masker.config._default_paths", lambda: ())

    assert load_project_config() == {}
