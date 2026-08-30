"""Загрузка безопасной конфигурации поставщика LLM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Настройки LLM без секретного значения ключа."""

    provider: str = "fake"
    model: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"
    timeout_seconds: float = 60.0
    site_url: str = ""
    title: str = "triema-masker"


def load_llm_config(path: Path) -> LLMConfig:
    """Прочитать YAML-конфигурацию, не подставляя в неё секреты."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"не удалось прочитать конфиг LLM {path}: {error}") from error
    except yaml.YAMLError as error:
        raise ValueError(f"некорректный YAML в конфиге LLM {path}: {error}") from error
    if not isinstance(raw, dict):
        raise ValueError("конфиг LLM должен быть YAML-объектом")
    settings: Any = raw.get("llm", raw)
    if not isinstance(settings, dict):
        raise ValueError("секция llm должна быть YAML-объектом")

    provider = _required_text(settings, "provider", default="fake").casefold()
    model = _required_text(settings, "model", default="")
    api_key_env = _required_text(settings, "api_key_env", default="OPENROUTER_API_KEY")
    site_url = _required_text(settings, "site_url", default="")
    title = _required_text(settings, "title", default="triema-masker")
    timeout = settings.get("timeout_seconds", 60.0)
    if not isinstance(timeout, int | float) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("llm.timeout_seconds должен быть положительным числом")
    if provider == "openrouter" and not model:
        raise ValueError("для llm.provider=openrouter укажите llm.model")
    if not api_key_env.isidentifier():
        raise ValueError("llm.api_key_env должен быть именем переменной окружения")
    return LLMConfig(
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        timeout_seconds=float(timeout),
        site_url=site_url,
        title=title,
    )


def _required_text(settings: dict[str, Any], key: str, *, default: str) -> str:
    value = settings.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"llm.{key} должен быть строкой")
    return value.strip()
