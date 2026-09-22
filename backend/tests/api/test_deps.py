"""Юнит-тесты зависимостей api.core.deps: get_current_user и require_admin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from api.core.deps import get_current_user, require_admin
from api.core.security import create_access_token
from api.models.user import UserORM


def _make_user(roles: list[str], is_active: bool = True) -> UserORM:
    return UserORM(
        id=uuid.uuid4(),
        email="dep@example.com",
        password_hash="hash",
        full_name="Dep User",
        roles=roles,
        is_active=is_active,
        created_at=datetime.now(UTC),
    )


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.asyncio
async def test_get_current_user_no_credentials():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None, session=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Не авторизован"


@pytest.mark.asyncio
async def test_get_current_user_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=_bearer("garbage-token"), session=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Невалидный или просроченный токен"


@pytest.mark.asyncio
async def test_get_current_user_malformed_subject_claim():
    """`sub` не-UUID (битый/старого формата токен) — это 401, а не необработанный 500."""
    token = create_access_token("not-a-uuid", ["user"])

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=_bearer(token), session=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Невалидный или просроченный токен"


@pytest.mark.asyncio
async def test_get_current_user_not_found(mocker):
    mocker.patch("api.core.deps.get_user_by_id", return_value=None)
    token = create_access_token(str(uuid.uuid4()), ["user"])

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=_bearer(token), session=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Пользователь не найден или деактивирован"


@pytest.mark.asyncio
async def test_get_current_user_inactive(mocker):
    user = _make_user(["user"], is_active=False)
    mocker.patch("api.core.deps.get_user_by_id", return_value=user)
    token = create_access_token(str(user.id), user.roles)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=_bearer(token), session=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_success(mocker):
    user = _make_user(["user"])
    mocker.patch("api.core.deps.get_user_by_id", return_value=user)
    token = create_access_token(str(user.id), user.roles)

    result = await get_current_user(credentials=_bearer(token), session=None)

    assert result is user


@pytest.mark.asyncio
async def test_require_admin_forbidden_for_regular_user():
    user = _make_user(["user"])

    with pytest.raises(HTTPException) as exc_info:
        await require_admin(user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Недостаточно прав"


@pytest.mark.asyncio
async def test_require_admin_allows_admin():
    user = _make_user(["admin"])

    result = await require_admin(user=user)

    assert result is user
