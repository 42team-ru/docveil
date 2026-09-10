"""Бизнес-логика управления пользователями (доступно только администраторам)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password, verify_password
from api.models.user import UserORM
from api.schemas.user import UserCreate


async def email_exists(session: AsyncSession, email: str) -> bool:
    result = await session.execute(select(UserORM.id).where(UserORM.email == email))
    return result.scalar_one_or_none() is not None


async def create_user(session: AsyncSession, payload: UserCreate) -> UserORM:
    user = UserORM(
        id=uuid.uuid4(),
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        roles=[role.value for role in payload.roles],
        is_active=True,
        created_at=datetime.now(UTC),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def reset_password(session: AsyncSession, email: str, password: str) -> UserORM | None:
    """Сменить пароль пользователя по email и вернуть его, если он существует."""
    result = await session.execute(select(UserORM).where(UserORM.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    user.password_hash = hash_password(password)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[UserORM]:
    result = await session.execute(select(UserORM).order_by(UserORM.created_at))
    return list(result.scalars().all())


async def update_profile(
    session: AsyncSession,
    user: UserORM,
    *,
    full_name: str | None = None,
    timezone: str | None = None,
) -> UserORM:
    """Self-service правка своих данных (`PATCH /auth/me`).

    Поля независимы: `None` значит «не трогать это поле», а не «очистить» —
    иначе выбор часового пояса стирал бы ещё не сохранённый черновик имени
    и наоборот, раз форма шлёт их отдельными запросами.
    """
    if full_name is not None:
        user.full_name = full_name
    if timezone is not None:
        user.timezone = timezone
    await session.commit()
    await session.refresh(user)
    return user


async def set_avatar(session: AsyncSession, user: UserORM, object_name: str) -> UserORM:
    """Self-service загрузка/замена аватара (`POST /auth/me/avatar`)."""
    user.avatar_object_name = object_name
    await session.commit()
    await session.refresh(user)
    return user


async def clear_avatar(session: AsyncSession, user: UserORM) -> UserORM:
    """Self-service удаление аватара (`DELETE /auth/me/avatar`)."""
    user.avatar_object_name = None
    await session.commit()
    await session.refresh(user)
    return user


async def change_password(
    session: AsyncSession,
    user: UserORM,
    current_password: str,
    new_password: str,
) -> None:
    """Self-service смена пароля (`POST /auth/me/password`)."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный текущий пароль")
    user.password_hash = hash_password(new_password)
    await session.commit()
