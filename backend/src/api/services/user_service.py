"""Бизнес-логика управления пользователями (доступно только администраторам)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import hash_password
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
