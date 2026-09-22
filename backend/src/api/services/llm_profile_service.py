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
from api.schemas.llm_profile import LLMPricingIn, LLMProfileCreate, LLMProfileOut
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
        pricing=pricing_from_dict(row.pricing) if row.pricing else None,
    )


async def _active_pointer(session: AsyncSession) -> LLMActiveSettingORM | None:
    return await session.get(LLMActiveSettingORM, _ACTIVE_SETTING_ID)


async def list_profiles(session: AsyncSession) -> list[LLMProfileOut]:
    active = await _active_pointer(session)
    active_source = active.source if active is not None else "builtin"
    active_name = (
        active.name if active is not None else (project_section("llm").get("profile") or "")
    )

    result: list[LLMProfileOut] = []
    for name in _builtin_names():
        config = _builtin_config(name)
        result.append(
            LLMProfileOut(
                id=None,
                source="builtin",
                name=name,
                provider=config.provider,
                model=config.model,
                api_key_env=config.api_key_env,
                provider_config={},
                pricing=_pricing_out(config.pricing),
                is_active=(active_source == "builtin" and active_name == name),
                created_at=None,
            )
        )

    rows = (
        (await session.execute(select(LLMProfileORM).order_by(LLMProfileORM.created_at)))
        .scalars()
        .all()
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
                provider_config=row.provider_config,
                pricing=LLMPricingIn.model_validate(row.pricing) if row.pricing else None,
                is_active=(active_source == "custom" and active_name == row.name),
                created_at=row.created_at,
            )
        )
    return result


async def create_profile(session: AsyncSession, payload: LLMProfileCreate) -> LLMProfileOut:
    if payload.name in _builtin_names():
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"имя {payload.name!r} занято встроенным профилем"
        )
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
        provider_config=row.provider_config,
        pricing=payload.pricing,
        is_active=False,
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
        return llm_config_from_mapping(settings)

    if active.source == "custom":
        row = await session.scalar(select(LLMProfileORM).where(LLMProfileORM.name == active.name))
        if row is not None:
            return _config_from_row(row)
        # Активная запись показывает на удалённый профиль — не должно
        # случаться (delete_profile это запрещает), но не 500 на прогон.

    if active.name in settings.get("profiles", {}):
        return llm_config_from_mapping({**settings, "profile": active.name})

    return llm_config_from_mapping(settings)
