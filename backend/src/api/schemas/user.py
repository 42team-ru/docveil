"""Доменная модель пользователя веб-слоя (не пересекается с masker.model)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, field_validator


class Role(StrEnum):
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
    #: IANA-имя пояса (`Europe/Moscow`); `None` — не выбран, фронт решает сам,
    #: что показывать по умолчанию.
    timezone: str | None = None
    #: Есть ли загруженный аватар — сам файл отдаёт `GET /auth/me/avatar`.
    has_avatar: bool = False


class UserSelfUpdate(BaseModel):
    """Тело запроса `PATCH /auth/me` — правка своих же данных.

    Оба поля необязательны и применяются независимо: форма профиля шлёт
    только то, что изменилось (имя — по кнопке «Сохранить», пояс — сразу по
    выбору в списке), а не всегда пару целиком.
    """

    full_name: str | None = None
    timezone: str | None = None

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            raise ValueError(f"неизвестный часовой пояс: {value!r}")
        return value


class PasswordChangeRequest(BaseModel):
    """Тело запроса `POST /auth/me/password`."""

    current_password: str
    new_password: str
