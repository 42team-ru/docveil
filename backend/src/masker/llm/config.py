"""Загрузка безопасной конфигурации поставщика LLM."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from masker.telemetry import LLMPricing, pricing_from_dict


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Настройки LLM; секрет профиля не попадает в repr конфигурации."""

    provider: str = "fake"
    profile: str = ""
    model: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"
    api_key: str = field(default="", repr=False, compare=False)
    timeout_seconds: float = 60.0
    site_url: str = ""
    title: str = "triema-masker"
    cassette_directory: str = ""
    openrouter_temperature: float = 0.0
    openrouter_provider_order: tuple[str, ...] = ()
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_temperature: float = 0.0001
    gigachat_ca_bundle_file: str = ""
    gigachat_insecure_skip_tls_verify: bool = False
    #: Локальный сервер Ollama обычно не требует ключа — своя секция вместо
    #: `api_key_env`, по аналогии с `openrouter`/`gigachat`.
    ollama_base_url: str = "http://localhost:11434"
    pricing: LLMPricing | None = None


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
    """Собрать LLMConfig из секции ``llm`` общего либо прежнего YAML-файла.

    Новый формат выбирает один именованный профиль из ``llm.profiles``.
    Профиль хранит вместе поставщика, модель и тариф, чтобы смена модели не
    оставляла в отчёте цену от предыдущей. Плоский формат остаётся рабочим
    для уже развёрнутых конфигов.
    """
    if not isinstance(settings, dict):
        raise ValueError("секция llm должна быть YAML-объектом")

    # Профиль выбирается окружением сильнее, чем YAML: в контейнере файл
    # приезжает вместе с образом, и поменять в нём строку — значит пересобрать
    # образ. `MASKER_LLM` при этом подменяет только ПРОВАЙДЕРА, оставляя
    # модель пустой, и развёртывание падало с «для GigaChat задайте модель»
    # при готовом профиле `gigachat` в том же файле (стенд, 14.09.2026).
    profile = os.environ.get("MASKER_LLM_PROFILE", "").strip() or _required_text(
        settings, "profile", default=""
    )
    selected = _profile_settings(settings, profile) if profile else settings
    provider = _required_text(selected, "provider", default="fake").casefold()
    model = _required_text(selected, "model", default="")
    api_key_env = _required_text(selected, "api_key_env", default="OPENROUTER_API_KEY")
    site_url = _required_text(selected, "site_url", default="")
    title = _required_text(selected, "title", default="triema-masker")
    pricing = pricing_from_dict(selected.get("pricing"))
    timeout = _positive_number(selected, "timeout_seconds", default=60.0)
    cassette_directory = _required_text(selected, "cassette_directory", default="")
    openrouter = _merged_mapping(settings, selected, "openrouter")
    gigachat = _merged_mapping(settings, selected, "gigachat")
    openrouter_temperature = _number(openrouter, "temperature", default=0.0)
    raw_order = openrouter.get("provider_order") or ()
    if isinstance(raw_order, str):
        raw_order = [raw_order]
    if not isinstance(raw_order, list | tuple):
        raise ValueError("llm.openrouter.provider_order должен быть строкой или списком строк")
    openrouter_provider_order = tuple(str(item).strip() for item in raw_order if str(item).strip())
    gigachat_scope = _required_text(gigachat, "scope", default="GIGACHAT_API_PERS")
    gigachat_temperature = _number(gigachat, "temperature", default=0.0001)
    gigachat_ca_bundle_file = _required_text(gigachat, "ca_bundle_file", default="")
    gigachat_insecure_skip_tls_verify = _boolean(
        gigachat, "insecure_skip_tls_verify", default=False
    )
    ollama = _merged_mapping(settings, selected, "ollama")
    ollama_base_url = _required_text(ollama, "base_url", default="http://localhost:11434")
    if provider == "openrouter" and not model:
        raise ValueError("для llm.provider=openrouter укажите llm.model")
    if not api_key_env.isidentifier():
        raise ValueError("llm.api_key_env должен быть именем переменной окружения")
    return LLMConfig(
        provider=provider,
        profile=profile,
        model=model,
        api_key_env=api_key_env,
        timeout_seconds=timeout,
        site_url=site_url,
        title=title,
        cassette_directory=cassette_directory,
        openrouter_temperature=openrouter_temperature,
        openrouter_provider_order=openrouter_provider_order,
        gigachat_scope=gigachat_scope,
        gigachat_temperature=gigachat_temperature,
        gigachat_ca_bundle_file=gigachat_ca_bundle_file,
        gigachat_insecure_skip_tls_verify=gigachat_insecure_skip_tls_verify,
        ollama_base_url=ollama_base_url,
        pricing=pricing,
    )


def _profile_settings(settings: dict[str, Any], profile: str) -> dict[str, Any]:
    """Наложить выбранный профиль на общие поля ``llm``."""
    profiles = _mapping(settings, "profiles")
    selected = profiles.get(profile)
    if not isinstance(selected, dict):
        raise ValueError(f"llm.profile={profile!r} отсутствует в llm.profiles")
    # Общие поля (например timeout) можно определить один раз наверху, а
    # профиль переопределяет их без копирования. ``profiles`` не должен
    # попадать в итоговую плоскую настройку.
    return {key: value for key, value in settings.items() if key != "profiles"} | selected


def _merged_mapping(defaults: dict[str, Any], selected: dict[str, Any], key: str) -> dict[str, Any]:
    """Слить общую и профильную вложенные секции параметров провайдера."""
    return _mapping(defaults, key) | _mapping(selected, key)


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
