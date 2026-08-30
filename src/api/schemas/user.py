"""Доменная модель пользователя веб-слоя (не пересекается с masker.model)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Role(str, Enum):
    ADMIN = "admin"
    USER = "user"


class User(BaseModel):
    id: UUID
    email: str
    password_hash: str
    full_name: str
    roles: list[Role]
    is_active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    """Тело запроса создания пользователя администратором."""

    email: str
    password: str
    full_name: str
    roles: list[Role] = [Role.USER]


class UserPublic(BaseModel):
    """Публичное представление пользователя — без password_hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    roles: list[Role]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
