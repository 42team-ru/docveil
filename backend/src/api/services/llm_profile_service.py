"""Настройки LLM-профиля: список (встроенные из YAML + свои из БД), CRUD
своих, переключение активного.

БД-логика живёт строго здесь, не в `masker/llm/*` — тот пакет намеренно не
знает о БД/API (см. докстринг `masker/config.py`): CLI обязан работать без
веб-слоя. Активный профиль из БД — промежуточный слой поверх YAML-дефолта;
переменные окружения (`MASKER_LLM*`) по-прежнему сильнее всего, потому что
итоговый `LLMConfig` отсюда всё равно проходит через `masker.llm.get_provider`
→ `resolve_llm_config`, который накладывает их как обычно.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.llm_profile import LLMActiveSettingORM, LLMProfileORM
from api.schemas.llm_profile import (
    LLMPricingIn,
    LLMProfileCreate,
    LLMProfileOut,
    LLMProfileUpdate,
)
from masker.config import project_section
from masker.llm.config import LLMConfig, llm_config_from_mapping
from masker.telemetry import LLMPricing, pricing_from_dict

_ACTIVE_SETTING_ID = 1


def _builtin_names() -> list[str]:
    return list(project_section("llm").get("profiles", {}).keys())


def _builtin_config(name: str) -> LLMConfig:
    settings = project_section("llm")
    if name not in settings.get("profiles", {}):
        raise ValueError(f"встроенный профиль {name!r} не найден в masker.yaml")
    return llm_config_from_mapping({**settings, "profile": name})


def _pricing_out(pricing: LLMPricing | None) -> LLMPricingIn | None:
    if pricing is None or not pricing.configured:
        return None
    data = pricing.as_dict()
    return LLMPricingIn(
        prompt_per_1k=float(data["prompt_per_1k"]),  # type: ignore[arg-type]
        completion_per_1k=float(data["completion_per_1k"]),  # type: ignore[arg-type]
        currency=str(data["currency"]),
        verified_at=str(data["verified_at"]),
    )


def _config_from_row(row: LLMProfileORM) -> LLMConfig:
    """`LLMConfig` из строки БД. `provider_config` — плоский словарь ключей
    `LLMConfig` (не вложенные `openrouter:`/`gigachat:` секции YAML — так
    проще собрать форму в GUI), непонятные ключи игнорируются."""
    cfg: dict[str, Any] = row.provider_config or {}
    defaults = LLMConfig()
    return LLMConfig(
        provider=row.provider,
        profile=row.name,
        model=row.model,
        api_key_env=row.api_key_env,
        api_key=row.api_key or "",
        timeout_seconds=float(cfg.get("timeout_seconds", defaults.timeout_seconds)),
        site_url=str(cfg.get("site_url", defaults.site_url)),
        title=str(cfg.get("title", defaults.title)),
        cassette_directory=str(cfg.get("cassette_directory", defaults.cassette_directory)),
        openrouter_temperature=float(
            cfg.get("openrouter_temperature", defaults.openrouter_temperature)
        ),
        openrouter_provider_order=tuple(cfg.get("openrouter_provider_order", ())),
        gigachat_scope=str(cfg.get("gigachat_scope", defaults.gigachat_scope)),
        gigachat_temperature=float(cfg.get("gigachat_temperature", defaults.gigachat_temperature)),
        gigachat_ca_bundle_file=str(
            cfg.get("gigachat_ca_bundle_file", defaults.gigachat_ca_bundle_file)
        ),
        gigachat_insecure_skip_tls_verify=bool(
            cfg.get("gigachat_insecure_skip_tls_verify", defaults.gigachat_insecure_skip_tls_verify)
        ),
        ollama_base_url=str(cfg.get("ollama_base_url", defaults.ollama_base_url)),
        pricing=pricing_from_dict(row.pricing) if row.pricing else None,
    )


def _provider_config_out(config: LLMConfig) -> dict[str, object]:
    """Без секретов сериализовать настройки профиля для формы редактирования."""
    return {
        "timeout_seconds": config.timeout_seconds,
        "site_url": config.site_url,
        "title": config.title,
        "cassette_directory": config.cassette_directory,
        "openrouter_temperature": config.openrouter_temperature,
        "openrouter_provider_order": list(config.openrouter_provider_order),
        "gigachat_scope": config.gigachat_scope,
        "gigachat_temperature": config.gigachat_temperature,
        "gigachat_ca_bundle_file": config.gigachat_ca_bundle_file,
        "gigachat_insecure_skip_tls_verify": config.gigachat_insecure_skip_tls_verify,
        "ollama_base_url": config.ollama_base_url,
    }


async def _active_pointer(session: AsyncSession) -> LLMActiveSettingORM | None:
    return await session.get(LLMActiveSettingORM, _ACTIVE_SETTING_ID)


async def list_profiles(session: AsyncSession) -> list[LLMProfileOut]:
    active = await _active_pointer(session)
    active_source = active.source if active is not None else "builtin"
    active_name = (
        active.name if active is not None else (project_section("llm").get("profile") or "")
    )

    rows = (
        (await session.execute(select(LLMProfileORM).order_by(LLMProfileORM.created_at)))
        .scalars()
        .all()
    )
    builtin_names = set(_builtin_names())
    overridden_names = {row.name for row in rows if row.name in builtin_names}
    result: list[LLMProfileOut] = []
    for name in _builtin_names():
        if name in overridden_names:
            continue
        config = _builtin_config(name)
        result.append(
            LLMProfileOut(
                id=None,
                source="builtin",
                name=name,
                provider=config.provider,
                model=config.model,
                api_key_env=config.api_key_env,
                has_api_key=False,
                provider_config=_provider_config_out(config),
                pricing=_pricing_out(config.pricing),
                is_active=(active_source == "builtin" and active_name == name),
                created_at=None,
            )
        )

    for row in rows:
        result.append(
            LLMProfileOut(
                id=row.id,
                source="custom",
                name=row.name,
                provider=row.provider,
                model=row.model,
                api_key_env=row.api_key_env,
                has_api_key=bool(row.api_key),
                provider_config=row.provider_config,
                pricing=LLMPricingIn.model_validate(row.pricing) if row.pricing else None,
                is_active=(active_name == row.name),
                created_at=row.created_at,
            )
        )
    return result


async def create_profile(session: AsyncSession, payload: LLMProfileCreate) -> LLMProfileOut:
    # Совпадение со встроенным именем — пользовательское переопределение.
    # list_profiles скрывает исходную YAML-строку, удаление возвращает её.
    exists = await session.scalar(
        select(LLMProfileORM.id).where(LLMProfileORM.name == payload.name)
    )
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"профиль {payload.name!r} уже существует")

    row = LLMProfileORM(
        id=uuid.uuid4(),
        name=payload.name,
        provider=payload.provider,
        model=payload.model,
        api_key_env=payload.api_key_env,
        api_key=payload.api_key or None,
        provider_config=payload.provider_config,
        pricing=payload.pricing.model_dump() if payload.pricing else None,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return LLMProfileOut(
        id=row.id,
        source="custom",
        name=row.name,
        provider=row.provider,
        model=row.model,
        api_key_env=row.api_key_env,
        has_api_key=bool(row.api_key),
        provider_config=row.provider_config,
        pricing=payload.pricing,
        is_active=False,
        created_at=row.created_at,
    )


async def update_profile(
    session: AsyncSession, profile_id: uuid.UUID, payload: LLMProfileUpdate
) -> LLMProfileOut:
    """Править свой профиль на месте — имя не меняется (см. `LLMProfileUpdate`).

    Если профиль сейчас активен, новые поля вступают в силу немедленно на
    следующем запросе: `resolve_active_llm_config` каждый раз читает строку
    заново, ничего не кеширует."""
    row = await session.get(LLMProfileORM, profile_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "профиль не найден")

    row.provider = payload.provider
    row.model = payload.model
    row.api_key_env = payload.api_key_env
    if "api_key" in payload.model_fields_set:
        # Поле прислано явно — либо новый токен, либо очистка (""/null).
        # Отсутствие поля в теле запроса оставляет сохранённый токен как есть.
        row.api_key = payload.api_key or None
    row.provider_config = payload.provider_config
    row.pricing = payload.pricing.model_dump() if payload.pricing else None
    await session.commit()
    await session.refresh(row)

    active = await _active_pointer(session)
    is_active = active is not None and active.source == "custom" and active.name == row.name
    return LLMProfileOut(
        id=row.id,
        source="custom",
        name=row.name,
        provider=row.provider,
        model=row.model,
        api_key_env=row.api_key_env,
        has_api_key=bool(row.api_key),
        provider_config=row.provider_config,
        pricing=payload.pricing,
        is_active=is_active,
        created_at=row.created_at,
    )


async def delete_profile(session: AsyncSession, profile_id: uuid.UUID) -> None:
    row = await session.get(LLMProfileORM, profile_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "профиль не найден")
    active = await _active_pointer(session)
    if active is not None and active.source == "custom" and active.name == row.name:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "нельзя удалить активный профиль — сначала переключите"
        )
    await session.delete(row)
    await session.commit()


async def set_active(session: AsyncSession, source: str, name: str) -> None:
    if source == "builtin":
        if name not in _builtin_names():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"встроенный профиль {name!r} не найден")
    else:
        exists = await session.scalar(select(LLMProfileORM.id).where(LLMProfileORM.name == name))
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"профиль {name!r} не найден")

    row = await _active_pointer(session)
    if row is None:
        session.add(
            LLMActiveSettingORM(
                id=_ACTIVE_SETTING_ID, source=source, name=name, updated_at=datetime.now(UTC)
            )
        )
    else:
        row.source = source
        row.name = name
        row.updated_at = datetime.now(UTC)
    await session.commit()


async def resolve_active_llm_config(session: AsyncSession) -> LLMConfig:
    """`LLMConfig` активного профиля — единственная точка, которую зовут
    FastAPI-зависимости (`run_service.get_llm_provider`,
    `custom_types_service.get_llm_provider`) вместо прямого
    `masker.llm.get_provider()` без аргументов."""
    settings = project_section("llm")
    active = await _active_pointer(session)
    if active is None:
        active_name = str(settings.get("profile") or "")
        row = await session.scalar(select(LLMProfileORM).where(LLMProfileORM.name == active_name))
        if row is not None:
            return _config_from_row(row)
        return llm_config_from_mapping(settings)

    if active.source == "custom":
        row = await session.scalar(select(LLMProfileORM).where(LLMProfileORM.name == active.name))
        if row is not None:
            return _config_from_row(row)
        # Активная запись показывает на удалённый профиль — не должно
        # случаться (delete_profile это запрещает), но не 500 на прогон.

    if active.name in settings.get("profiles", {}):
        row = await session.scalar(select(LLMProfileORM).where(LLMProfileORM.name == active.name))
        if row is not None:
            return _config_from_row(row)
        return llm_config_from_mapping({**settings, "profile": active.name})

    return llm_config_from_mapping(settings)
