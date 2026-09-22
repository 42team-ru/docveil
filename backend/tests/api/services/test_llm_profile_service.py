"""Юнит-тесты api.services.llm_profile_service.

`neutral_project_config` (autouse, tests/api/conftest.py) даёт ровно один
встроенный профиль — `fake` (`llm.profile: fake`, `llm.profiles.fake.provider:
fake`) — на нём и построены тесты списка/резолвера, без похода в реальный
masker.yaml разработчика.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.models.llm_profile import LLMActiveSettingORM, LLMProfileORM
from api.schemas.llm_profile import LLMProfileCreate, LLMProfileUpdate
from api.services.llm_profile_service import (
    create_profile,
    delete_profile,
    list_profiles,
    resolve_active_llm_config,
    set_active,
    update_profile,
)


def _custom_row(**overrides) -> LLMProfileORM:
    defaults = dict(
        id=uuid.uuid4(),
        name="my-openrouter",
        provider="openrouter",
        model="deepseek/deepseek-chat",
        api_key_env="OPENROUTER_API_KEY",
        provider_config={},
        pricing=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return LLMProfileORM(**defaults)


def _session_with(*, get_result=None, scalar_result=None, scalars_all=None) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=get_result)
    session.scalar = AsyncMock(return_value=scalar_result)
    execute_result = MagicMock()
    scalars_result = MagicMock(all=MagicMock(return_value=scalars_all or []))
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_list_profiles_includes_builtin_and_marks_default_active():
    session = _session_with(get_result=None, scalars_all=[])

    profiles = await list_profiles(session)

    assert [p.name for p in profiles] == ["fake"]
    assert profiles[0].source == "builtin"
    assert profiles[0].is_active is True
    assert profiles[0].id is None


@pytest.mark.asyncio
async def test_list_profiles_includes_custom_rows_and_marks_active_one():
    row = _custom_row(name="my-openrouter")
    active = LLMActiveSettingORM(
        id=1, source="custom", name="my-openrouter", updated_at=datetime.now(UTC)
    )
    session = _session_with(get_result=active, scalars_all=[row])

    profiles = await list_profiles(session)

    names = {p.name: p for p in profiles}
    assert set(names) == {"fake", "my-openrouter"}
    assert names["fake"].is_active is False
    assert names["my-openrouter"].is_active is True
    assert names["my-openrouter"].source == "custom"
    assert names["my-openrouter"].id == row.id


@pytest.mark.asyncio
async def test_create_profile_rejects_name_colliding_with_builtin():
    session = _session_with()
    payload = LLMProfileCreate(name="fake", provider="openrouter", model="x")

    with pytest.raises(HTTPException) as exc_info:
        await create_profile(session, payload)

    assert exc_info.value.status_code == 409
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_profile_rejects_duplicate_custom_name():
    session = _session_with(scalar_result=uuid.uuid4())
    payload = LLMProfileCreate(name="my-openrouter", provider="openrouter", model="x")

    with pytest.raises(HTTPException) as exc_info:
        await create_profile(session, payload)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_profile_persists_and_returns_custom_profile():
    session = _session_with(scalar_result=None)
    payload = LLMProfileCreate(
        name="my-openrouter", provider="openrouter", model="deepseek/deepseek-chat"
    )

    result = await create_profile(session, payload)

    assert result.name == "my-openrouter"
    assert result.source == "custom"
    assert result.is_active is False
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_profile_rejects_missing_profile():
    session = _session_with(get_result=None)

    with pytest.raises(HTTPException) as exc_info:
        await delete_profile(session, uuid.uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_profile_rejects_currently_active_profile():
    row = _custom_row(name="my-openrouter")
    active = LLMActiveSettingORM(
        id=1, source="custom", name="my-openrouter", updated_at=datetime.now(UTC)
    )
    # get() отвечает и за строку профиля, и за указатель активного — по порядку вызовов.
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[row, active])

    with pytest.raises(HTTPException) as exc_info:
        await delete_profile(session, row.id)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_set_active_rejects_unknown_builtin_name():
    session = _session_with()

    with pytest.raises(HTTPException) as exc_info:
        await set_active(session, "builtin", "does-not-exist")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_active_rejects_unknown_custom_name():
    session = _session_with(scalar_result=None)

    with pytest.raises(HTTPException) as exc_info:
        await set_active(session, "custom", "does-not-exist")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_set_active_creates_pointer_when_none_exists():
    session = _session_with(get_result=None)

    await set_active(session, "builtin", "fake")

    session.add.assert_called_once()
    added = session.add.call_args.args[0]
    assert isinstance(added, LLMActiveSettingORM)
    assert added.source == "builtin"
    assert added.name == "fake"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_active_llm_config_defaults_to_yaml_profile_without_pointer():
    session = _session_with(get_result=None)

    config = await resolve_active_llm_config(session)

    assert config.provider == "fake"
    assert config.profile == "fake"


@pytest.mark.asyncio
async def test_resolve_active_llm_config_uses_custom_profile_fields():
    row = _custom_row(
        name="my-openrouter",
        provider="openrouter",
        model="deepseek/deepseek-chat",
        api_key_env="MY_KEY_ENV",
    )
    active = LLMActiveSettingORM(
        id=1, source="custom", name="my-openrouter", updated_at=datetime.now(UTC)
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=active)
    session.scalar = AsyncMock(return_value=row)

    config = await resolve_active_llm_config(session)

    assert config.provider == "openrouter"
    assert config.model == "deepseek/deepseek-chat"
    assert config.api_key_env == "MY_KEY_ENV"
    assert config.profile == "my-openrouter"


@pytest.mark.asyncio
async def test_update_profile_rejects_missing_profile():
    session = _session_with(get_result=None)
    payload = LLMProfileUpdate(provider="openrouter", model="new-model")

    with pytest.raises(HTTPException) as exc_info:
        await update_profile(session, uuid.uuid4(), payload)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_persists_new_fields():
    row = _custom_row(name="my-openrouter", provider="openrouter", model="old-model")
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[row, None])
    payload = LLMProfileUpdate(provider="openrouter", model="new-model", api_key_env="NEW_ENV")

    result = await update_profile(session, row.id, payload)

    assert row.model == "new-model"
    assert row.api_key_env == "NEW_ENV"
    assert result.model == "new-model"
    assert result.is_active is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_profile_reports_active_when_currently_active():
    row = _custom_row(name="my-openrouter")
    active = LLMActiveSettingORM(
        id=1, source="custom", name="my-openrouter", updated_at=datetime.now(UTC)
    )
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[row, active])
    payload = LLMProfileUpdate(provider="openrouter", model="new-model")

    result = await update_profile(session, row.id, payload)

    assert result.is_active is True
