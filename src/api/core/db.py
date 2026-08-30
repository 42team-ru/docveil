"""Настройка SQLAlchemy для Postgres.

Отдельный контур от пайплайна LangGraph: здесь живёт хранение пользователей
и прочих сущностей веб-слоя, а не контракты `masker.model`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from api.core.config import settings


class Base(DeclarativeBase):
    """Базовый класс для ORM-моделей веб-слоя."""


engine: AsyncEngine = create_async_engine(settings.database_url, future=True)

async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-зависимость: сессия БД на время запроса."""
    async with async_session_maker() as session:
        yield session


async def init_models() -> None:
    """Создать таблицы напрямую, без Alembic (для локальной разработки/тестов)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
