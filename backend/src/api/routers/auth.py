"""Роуты аутентификации: login/refresh/logout/me."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.core.db import get_db
from api.core.deps import get_current_user
from api.models.user import UserORM
from api.schemas.auth import DeviceType, LoginRequest, RefreshRequest, TokenResponse
from api.schemas.user import UserPublic
from api.services.auth_service import (
    authenticate_user,
    issue_tokens,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        expires=expires_at,
        path="/api/auth",
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await authenticate_user(session, payload.email, payload.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    access_token, refresh_token, expires_at = await issue_tokens(
        session, user, payload.device.value
    )
    if payload.device == DeviceType.WEB:
        _set_refresh_cookie(response, refresh_token, expires_at)
        return TokenResponse(access_token=access_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    payload: RefreshRequest | None = None,
    refresh_token_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token = refresh_token_cookie or (payload.refresh_token if payload else None)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-токен не передан")
    result = await rotate_refresh_token(session, token)
    if result is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Невалидный или просроченный refresh-токен"
        )
    _user, access_token, new_refresh_token, expires_at = result
    if refresh_token_cookie is not None:
        _set_refresh_cookie(response, new_refresh_token, expires_at)
        return TokenResponse(access_token=access_token)
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    payload: RefreshRequest | None = None,
    refresh_token_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    session: AsyncSession = Depends(get_db),
) -> None:
    token = refresh_token_cookie or (payload.refresh_token if payload else None)
    if token:
        await revoke_refresh_token(session, token)
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me", response_model=UserPublic)
async def me(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    return current_user
