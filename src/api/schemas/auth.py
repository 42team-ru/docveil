"""Схемы запросов/ответов для аутентификации."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DeviceType(StrEnum):
    """Тип клиента, выполняющего вход.

    WEB получает refresh-токен только в httponly-cookie; остальные — в теле ответа,
    чтобы сами отвечали за его хранение (secure storage на мобильном/десктопе).
    """

    WEB = "web"
    MOBILE = "mobile"
    DESKTOP = "desktop"


class LoginRequest(BaseModel):
    email: str
    password: str
    device: DeviceType = DeviceType.WEB


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Для не-WEB клиентов: передают refresh-токен явно, а не через cookie."""

    refresh_token: str | None = None
