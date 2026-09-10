"""Юнит-тесты api.services.user_service (создание/поиск пользователей)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.core.security import hash_password, verify_password
from api.models.user import UserORM
from api.schemas.user import Role, UserCreate
from api.services.user_service import (
    change_password,
    clear_avatar,
    create_user,
    email_exists,
    list_users,
    reset_password,
    set_avatar,
    update_profile,
)


def _session_returning(scalar_result):
    session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.mark.asyncio
async def test_email_exists_true():
    session = _session_returning(uuid.uuid4())

    assert await email_exists(session, "taken@example.com") is True


@pytest.mark.asyncio
async def test_email_exists_false():
    session = _session_returning(None)

    assert await email_exists(session, "free@example.com") is False


@pytest.mark.asyncio
async def test_create_user_hashes_password_and_persists():
    session = AsyncMock()
    session.add = MagicMock()  # AsyncSession.add() is synchronous, unlike execute/commit/refresh
    payload = UserCreate(
        email="new@example.com",
        password="plaintext-password",
        full_name="New Person",
        roles=[Role.USER],
    )

    user = await create_user(session, payload)

    assert user.email == "new@example.com"
    assert user.roles == ["user"]
    assert user.is_active is True
    assert user.password_hash != "plaintext-password"
    assert verify_password("plaintext-password", user.password_hash) is True
    session.add.assert_called_once_with(user)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_create_user_defaults_to_user_role():
    session = AsyncMock()
    session.add = MagicMock()
    payload = UserCreate(email="norole@example.com", password="pw", full_name="No Role")

    user = await create_user(session, payload)

    assert user.roles == ["user"]


@pytest.mark.asyncio
async def test_reset_password_hashes_new_value_and_persists():
    user = MagicMock(password_hash="old-hash")
    session = _session_returning(user)

    result = await reset_password(session, "taken@example.com", "new-password")

    assert result is user
    assert verify_password("new-password", user.password_hash) is True
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_reset_password_returns_none_for_missing_user():
    session = _session_returning(None)

    result = await reset_password(session, "missing@example.com", "new-password")

    assert result is None
    session.commit.assert_not_awaited()
    session.refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_users_returns_ordered_list():
    session = AsyncMock()
    execute_result = MagicMock()
    scalars_result = MagicMock(all=MagicMock(return_value=["u1", "u2"]))
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)

    result = await list_users(session)

    assert result == ["u1", "u2"]


def _make_user(**overrides) -> UserORM:
    defaults = dict(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash=hash_password("current-pass"),
        full_name="Old Name",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return UserORM(**defaults)


@pytest.mark.asyncio
async def test_update_profile_persists_full_name():
    session = AsyncMock()
    user = _make_user()

    result = await update_profile(session, user, full_name="New Name")

    assert result.full_name == "New Name"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_update_profile_persists_timezone():
    session = AsyncMock()
    user = _make_user()

    result = await update_profile(session, user, timezone="Europe/Moscow")

    assert result.timezone == "Europe/Moscow"


@pytest.mark.asyncio
async def test_update_profile_leaves_unset_fields_untouched():
    session = AsyncMock()
    user = _make_user(full_name="Kept Name", timezone="Europe/Moscow")

    await update_profile(session, user, full_name=None, timezone=None)

    assert user.full_name == "Kept Name"
    assert user.timezone == "Europe/Moscow"


@pytest.mark.asyncio
async def test_set_avatar_persists_object_name():
    session = AsyncMock()
    user = _make_user()

    result = await set_avatar(session, user, "abc123/photo.png")

    assert result.avatar_object_name == "abc123/photo.png"
    assert result.has_avatar is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_clear_avatar_removes_object_name():
    session = AsyncMock()
    user = _make_user(avatar_object_name="abc123/photo.png")

    result = await clear_avatar(session, user)

    assert result.avatar_object_name is None
    assert result.has_avatar is False


@pytest.mark.asyncio
async def test_change_password_updates_hash_on_correct_current_password():
    session = AsyncMock()
    user = _make_user()

    await change_password(session, user, "current-pass", "new-pass")

    assert verify_password("new-pass", user.password_hash) is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current_password():
    session = AsyncMock()
    user = _make_user()
    original_hash = user.password_hash

    with pytest.raises(HTTPException) as exc_info:
        await change_password(session, user, "wrong-pass", "new-pass")

    assert exc_info.value.status_code == 401
    assert user.password_hash == original_hash
    session.commit.assert_not_awaited()
