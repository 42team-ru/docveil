"""Юнит-тесты api.services.user_service (создание/поиск пользователей)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.security import verify_password
from api.schemas.user import Role, UserCreate
from api.services.user_service import create_user, email_exists, list_users


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
async def test_list_users_returns_ordered_list():
    session = AsyncMock()
    execute_result = MagicMock()
    scalars_result = MagicMock(all=MagicMock(return_value=["u1", "u2"]))
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)

    result = await list_users(session)

    assert result == ["u1", "u2"]
