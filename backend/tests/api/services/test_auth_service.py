"""Юнит-тесты api.services.auth_service (пароль, access/refresh токены, ротация, отзыв)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.security import decode_access_token, hash_password, hash_token
from api.models.refresh_token import RefreshTokenORM
from api.models.user import UserORM
from api.services.auth_service import (
    authenticate_user,
    get_user_by_id,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)


def _user(**overrides) -> UserORM:
    defaults = dict(
        id=uuid.uuid4(),
        email="auth@example.com",
        password_hash=hash_password("correct-password"),
        full_name="Auth User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return UserORM(**defaults)


def _session_with_scalar(scalar_result) -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.mark.asyncio
async def test_authenticate_user_success():
    user = _user()
    session = _session_with_scalar(user)

    result = await authenticate_user(session, user.email, "correct-password")

    assert result is user


@pytest.mark.asyncio
async def test_authenticate_user_wrong_password():
    user = _user()
    session = _session_with_scalar(user)

    result = await authenticate_user(session, user.email, "wrong-password")

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_user_not_found():
    session = _session_with_scalar(None)

    result = await authenticate_user(session, "missing@example.com", "any")

    assert result is None


@pytest.mark.asyncio
async def test_authenticate_user_inactive():
    user = _user(is_active=False)
    session = _session_with_scalar(user)

    result = await authenticate_user(session, user.email, "correct-password")

    assert result is None


@pytest.mark.asyncio
async def test_get_user_by_id_accepts_string_uuid():
    user = _user()
    session = AsyncMock()
    session.get = AsyncMock(return_value=user)

    result = await get_user_by_id(session, str(user.id))

    assert result is user
    session.get.assert_awaited_once_with(UserORM, user.id)


@pytest.mark.asyncio
async def test_issue_tokens_returns_valid_access_token_and_persists_refresh():
    user = _user()
    session = AsyncMock()
    session.add = MagicMock()

    access_token, refresh_token, expires_at = await issue_tokens(session, user, "web")

    payload = decode_access_token(access_token)
    assert payload["sub"] == str(user.id)
    assert payload["roles"] == user.roles
    assert isinstance(refresh_token, str) and len(refresh_token) > 20
    assert expires_at > datetime.now(UTC)

    session.add.assert_called_once()
    stored: RefreshTokenORM = session.add.call_args[0][0]
    assert stored.user_id == user.id
    assert stored.token_hash == hash_token(refresh_token)
    assert stored.device == "web"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rotate_refresh_token_success(mocker):
    user = _user()
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_token("old-refresh"),
        device="web",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=None,
    )
    session = _session_with_scalar(stored)
    session.get = AsyncMock(return_value=user)
    mocker.patch(
        "api.services.auth_service.issue_tokens",
        new_callable=AsyncMock,
        return_value=("new_access", "new_refresh", datetime.now(UTC) + timedelta(days=30)),
    )

    result = await rotate_refresh_token(session, "old-refresh")

    assert result is not None
    returned_user, access_token, new_refresh, _expires = result
    assert returned_user is user
    assert access_token == "new_access"
    assert new_refresh == "new_refresh"
    assert stored.revoked_at is not None


@pytest.mark.asyncio
async def test_rotate_refresh_token_unknown_token():
    session = _session_with_scalar(None)

    result = await rotate_refresh_token(session, "unknown")

    assert result is None


@pytest.mark.asyncio
async def test_rotate_refresh_token_already_revoked():
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=hash_token("revoked"),
        device="web",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=datetime.now(UTC),
    )
    session = _session_with_scalar(stored)

    result = await rotate_refresh_token(session, "revoked")

    assert result is None


@pytest.mark.asyncio
async def test_rotate_refresh_token_expired():
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=hash_token("expired"),
        device="web",
        created_at=datetime.now(UTC) - timedelta(days=40),
        expires_at=datetime.now(UTC) - timedelta(days=1),
        revoked_at=None,
    )
    session = _session_with_scalar(stored)

    result = await rotate_refresh_token(session, "expired")

    assert result is None


@pytest.mark.asyncio
async def test_rotate_refresh_token_inactive_user():
    user = _user(is_active=False)
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_token("token"),
        device="web",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=None,
    )
    session = _session_with_scalar(stored)
    session.get = AsyncMock(return_value=user)

    result = await rotate_refresh_token(session, "token")

    assert result is None


@pytest.mark.asyncio
async def test_revoke_refresh_token_marks_revoked():
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=hash_token("to-revoke"),
        device="web",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=None,
    )
    session = _session_with_scalar(stored)

    await revoke_refresh_token(session, "to-revoke")

    assert stored.revoked_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_refresh_token_unknown_is_noop():
    session = _session_with_scalar(None)

    await revoke_refresh_token(session, "unknown")

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_refresh_token_already_revoked_is_noop():
    stored = RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=hash_token("already"),
        device="web",
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
        revoked_at=datetime.now(UTC),
    )
    session = _session_with_scalar(stored)

    await revoke_refresh_token(session, "already")

    session.commit.assert_not_awaited()
