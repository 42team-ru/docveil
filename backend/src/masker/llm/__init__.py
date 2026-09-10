"""Поставщики языковых моделей."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from masker.config import project_section
from masker.llm.base import LLMError, LLMProvider, LLMUsage, Message
from masker.llm.cassette import CassetteProvider
from masker.llm.config import LLMConfig, llm_config_from_mapping, load_llm_config
from masker.llm.fake import FakeProvider
from masker.llm.gigachat import GigaChatProvider
from masker.llm.openrouter import OpenRouterProvider
from masker.llm.trace import BatchTrace, CallTrace, ProfileOutcome, TracingProvider, write_trace
from masker.telemetry import LLMPricing, pricing_from_dict

__all__ = [
    "BatchTrace",
    "CallTrace",
    "CassetteProvider",
    "FakeProvider",
    "GigaChatProvider",
    "LLMConfig",
    "LLMError",
    "LLMProvider",
    "LLMUsage",
    "Message",
    "OpenRouterProvider",
    "ProfileOutcome",
    "TracingProvider",
    "get_provider",
    "load_llm_config",
    "resolve_cli_llm",
    "resolve_llm_config",
    "write_trace",
]

# Переменная окружения с секретом по умолчанию для каждого провайдера.
# Используется только когда конфигурация строится из окружения
# (`get_provider()` без явного `LLMConfig`) — YAML-конфиг всегда указывает
# `api_key_env` явно через `load_llm_config`.
_DEFAULT_API_KEY_ENV_BY_PROVIDER: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "gigachat": "GIGACHAT_CREDENTIALS",
}

_DEFAULT_CASSETTE_DIRECTORY = Path(__file__).resolve().parents[3] / "fixtures" / "llm" / "roles"


def _read_number_env(env_var: str, default: float) -> float:
    """Прочитать необязательное число из окружения или вернуть нижний приоритет."""
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise LLMError(f"{env_var} должна быть числом, получено: {raw!r}") from error


def get_provider(config: LLMConfig | None = None) -> LLMProvider:
    """Создать LLM-поставщик (окружение → YAML → дефолт в коде)."""
    config = resolve_llm_config(config)
    provider = config.provider
    if provider == "fake":
        return FakeProvider()
    if provider == "cassette":
        directory = Path(config.cassette_directory or _DEFAULT_CASSETTE_DIRECTORY)
        return CassetteProvider(directory)
    if provider == "openrouter":
        api_key = os.environ.get(config.api_key_env, "")
        if not api_key:
            raise LLMError(
                f"не задана переменная окружения {config.api_key_env} с ключом OpenRouter"
            )
        if not config.model:
            raise LLMError("для OpenRouter задайте модель в конфиге или MASKER_LLM_MODEL")
        return OpenRouterProvider(
            api_key=api_key,
            model=config.model,
            temperature=config.openrouter_temperature,
            timeout_seconds=config.timeout_seconds,
            site_url=config.site_url,
            title=config.title,
            provider_order=config.openrouter_provider_order,
        )
    if provider == "gigachat":
        credentials = os.environ.get(config.api_key_env, "")
        if not credentials:
            raise LLMError(
                f"не задана переменная окружения {config.api_key_env} с ключом авторизации GigaChat"
            )
        if not config.model:
            raise LLMError("для GigaChat задайте модель в конфиге или MASKER_LLM_MODEL")
        return GigaChatProvider(
            credentials=credentials,
            model=config.model,
            scope=config.gigachat_scope,
            temperature=config.gigachat_temperature,
            timeout_seconds=config.timeout_seconds,
            ca_bundle_file=config.gigachat_ca_bundle_file or None,
            verify_ssl_certs=not config.gigachat_insecure_skip_tls_verify,
        )
    raise LLMError(f"неизвестный поставщик LLM: {provider!r}")


def resolve_cli_llm(
    llm_config_path: Path | None, *, allow_remote_pii: bool
) -> tuple[LLMProvider | None, LLMPricing | None]:
    """Резолвнуть LLM и тариф из CLI-опций (это конфигурация, не разбор argv).

    Без ``--llm-config`` берётся тариф дефолтной конфигурации без провайдера
    (совместимость с прогоном без LLM). Ошибки конфигурации и отсутствие
    ``--allow-remote-pii`` для удалённого провайдера уходят как ``LLMError``/
    ``ValueError`` — вызывающий CLI сам решает, как превратить их в
    ``parser.error``, чтобы поведение для пользователя не изменилось.
    """
    if llm_config_path is None:
        return None, resolve_llm_config().pricing
    config = resolve_llm_config(load_llm_config(llm_config_path))
    if config.provider != "fake" and not allow_remote_pii:
        raise LLMError("OpenRouter получит исходные PII и контекст; добавьте --allow-remote-pii")
    return get_provider(config), config.pricing


def resolve_llm_config(config: LLMConfig | None = None) -> LLMConfig:
    """Вернуть итоговую LLM-конфигурацию (окружение → YAML → дефолт)."""
    if config is None:
        config = llm_config_from_mapping(project_section("llm"))
    return _environment_overrides(config)


def _environment_overrides(config: LLMConfig) -> LLMConfig:
    """Наложить совместимые с прежним развёртыванием переменные на YAML."""
    provider = _read_text_env("MASKER_LLM", config.provider).casefold()
    # Профиль может сознательно назвать нестандартную переменную секрета.
    # Подменяем имя на стандартное только при прежнем сценарии: дефолтный
    # fake-профиль переключён через MASKER_LLM на реальный провайдер.
    api_key_env = config.api_key_env
    uses_legacy_default_key = config.provider == "fake" and api_key_env == "OPENROUTER_API_KEY"
    if provider != config.provider and uses_legacy_default_key:
        api_key_env = _DEFAULT_API_KEY_ENV_BY_PROVIDER.get(provider, api_key_env)
    return replace(
        config,
        provider=provider,
        model=_read_text_env("MASKER_LLM_MODEL", config.model),
        api_key_env=_read_text_env("MASKER_LLM_API_KEY_ENV", api_key_env),
        timeout_seconds=_read_number_env("MASKER_LLM_TIMEOUT_SECONDS", config.timeout_seconds),
        site_url=_read_text_env("MASKER_LLM_SITE_URL", config.site_url),
        title=_read_text_env("MASKER_LLM_TITLE", config.title),
        cassette_directory=_read_text_env("MASKER_LLM_CASSETTE_DIR", config.cassette_directory),
        openrouter_temperature=_read_number_env(
            "MASKER_LLM_OPENROUTER_TEMPERATURE", config.openrouter_temperature
        ),
        gigachat_scope=_read_text_env("MASKER_LLM_GIGACHAT_SCOPE", config.gigachat_scope),
        gigachat_temperature=_read_number_env(
            "MASKER_LLM_GIGACHAT_TEMPERATURE", config.gigachat_temperature
        ),
        gigachat_ca_bundle_file=_read_text_env(
            "MASKER_LLM_GIGACHAT_CA_BUNDLE", config.gigachat_ca_bundle_file
        ),
        gigachat_insecure_skip_tls_verify=_read_boolean_env(
            "MASKER_LLM_GIGACHAT_INSECURE_SKIP_TLS_VERIFY",
            config.gigachat_insecure_skip_tls_verify,
        ),
        pricing=_pricing_environment_overrides(config.pricing),
    )


def _read_text_env(env_var: str, default: str) -> str:
    value = os.environ.get(env_var)
    return default if value is None else value.strip()


def _read_boolean_env(env_var: str, default: bool) -> bool:
    value = os.environ.get(env_var)
    if value is None:
        return default
    return value.strip().casefold() in ("1", "true", "yes")


def _pricing_environment_overrides(pricing: LLMPricing | None) -> LLMPricing | None:
    """Наложить переменные окружения на тариф из YAML как на прочие LLM-поля."""
    values = pricing.as_dict() if pricing is not None else {}
    names = {
        "prompt_per_1k": "MASKER_LLM_PRICING_PROMPT_PER_1K",
        "completion_per_1k": "MASKER_LLM_PRICING_COMPLETION_PER_1K",
        "currency": "MASKER_LLM_PRICING_CURRENCY",
        "verified_at": "MASKER_LLM_PRICING_VERIFIED_AT",
    }
    if not any(name in os.environ for name in names.values()):
        return pricing
    for key, env_var in names.items():
        if env_var in os.environ:
            values[key] = os.environ[env_var].strip()
    return pricing_from_dict(values)
