"""Бизнес-логика аутентификации: пароль, access/refresh токены, ротация, отзыв."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)
from api.models.refresh_token import RefreshTokenORM
from api.models.user import UserORM


async def authenticate_user(session: AsyncSession, email: str, password: str) -> UserORM | None:
    """Вернуть пользователя, если email/пароль верны и аккаунт активен, иначе None."""
    result = await session.execute(select(UserORM).where(UserORM.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_user_by_id(session: AsyncSession, user_id: str | uuid.UUID) -> UserORM | None:
    if isinstance(user_id, str):
        user_id = uuid.UUID(user_id)
    return await session.get(UserORM, user_id)


async def issue_tokens(
    session: AsyncSession, user: UserORM, device: str
) -> tuple[str, str, datetime]:
    """Выдать пару access/refresh и время истечения refresh-токена."""
    access_token = create_access_token(str(user.id), user.roles)
    refresh_plain = generate_refresh_token()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    session.add(
        RefreshTokenORM(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=hash_token(refresh_plain),
            device=device,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
    )
    await session.execute(
        update(UserORM).where(UserORM.id == user.id).values(last_login_at=datetime.now(UTC))
    )
    await session.commit()
    return access_token, refresh_plain, expires_at


async def rotate_refresh_token(
    session: AsyncSession, refresh_plain: str
) -> tuple[UserORM, str, str, datetime] | None:
    """Проверить refresh-токен, отозвать его и выдать новую пару. None — токен невалиден."""
    token_hash = hash_token(refresh_plain)
    result = await session.execute(
        select(RefreshTokenORM).where(RefreshTokenORM.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if stored is None or stored.revoked_at is not None or stored.expires_at < datetime.now(UTC):
        return None
    user = await session.get(UserORM, stored.user_id)
    if user is None or not user.is_active:
        return None
    stored.revoked_at = datetime.now(UTC)
    access_token, new_refresh_plain, expires_at = await issue_tokens(session, user, stored.device)
    return user, access_token, new_refresh_plain, expires_at


async def revoke_refresh_token(session: AsyncSession, refresh_plain: str) -> None:
    """Отозвать один refresh-токен (logout текущего устройства)."""
    token_hash = hash_token(refresh_plain)
    result = await session.execute(
        select(RefreshTokenORM).where(RefreshTokenORM.token_hash == token_hash)
    )
    stored = result.scalar_one_or_none()
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        await session.commit()
