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
    cassette_directory: str = ""
    openrouter_temperature: float = 0.0
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_temperature: float = 0.0001
    gigachat_ca_bundle_file: str = ""
    gigachat_insecure_skip_tls_verify: bool = False


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
    return llm_config_from_mapping(settings)


def llm_config_from_mapping(settings: Any) -> LLMConfig:
    """Собрать LLMConfig из секции ``llm`` общего либо прежнего YAML-файла."""
    if not isinstance(settings, dict):
        raise ValueError("секция llm должна быть YAML-объектом")

    provider = _required_text(settings, "provider", default="fake").casefold()
    model = _required_text(settings, "model", default="")
    api_key_env = _required_text(settings, "api_key_env", default="OPENROUTER_API_KEY")
    site_url = _required_text(settings, "site_url", default="")
    title = _required_text(settings, "title", default="triema-masker")
    timeout = _positive_number(settings, "timeout_seconds", default=60.0)
    cassette_directory = _required_text(settings, "cassette_directory", default="")
    openrouter = _mapping(settings, "openrouter")
    gigachat = _mapping(settings, "gigachat")
    openrouter_temperature = _number(openrouter, "temperature", default=0.0)
    gigachat_scope = _required_text(gigachat, "scope", default="GIGACHAT_API_PERS")
    gigachat_temperature = _number(gigachat, "temperature", default=0.0001)
    gigachat_ca_bundle_file = _required_text(gigachat, "ca_bundle_file", default="")
    gigachat_insecure_skip_tls_verify = _boolean(
        gigachat, "insecure_skip_tls_verify", default=False
    )
    if provider == "openrouter" and not model:
        raise ValueError("для llm.provider=openrouter укажите llm.model")
    if not api_key_env.isidentifier():
        raise ValueError("llm.api_key_env должен быть именем переменной окружения")
    return LLMConfig(
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        timeout_seconds=timeout,
        site_url=site_url,
        title=title,
        cassette_directory=cassette_directory,
        openrouter_temperature=openrouter_temperature,
        gigachat_scope=gigachat_scope,
        gigachat_temperature=gigachat_temperature,
        gigachat_ca_bundle_file=gigachat_ca_bundle_file,
        gigachat_insecure_skip_tls_verify=gigachat_insecure_skip_tls_verify,
    )


def _required_text(settings: dict[str, Any], key: str, *, default: str) -> str:
    value = settings.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"llm.{key} должен быть строкой")
    return value.strip()


def _mapping(settings: dict[str, Any], key: str) -> dict[str, Any]:
    value = settings.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"llm.{key} должна быть YAML-объектом")
    return value


def _positive_number(settings: dict[str, Any], key: str, *, default: float) -> float:
    value = _number(settings, key, default=default)
    if value <= 0:
        raise ValueError(f"llm.{key} должен быть положительным числом")
    return value


def _number(settings: dict[str, Any], key: str, *, default: float) -> float:
    value = settings.get(key, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"llm.{key} должен быть числом")
    return float(value)


def _boolean(settings: dict[str, Any], key: str, *, default: bool) -> bool:
    value = settings.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"llm.{key} должен быть true или false")
    return value
