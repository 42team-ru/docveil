"""FastAPI-зависимости: текущий пользователь из access-токена, проверка роли."""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.db import get_db
from api.core.security import decode_access_token
from api.models.user import UserORM
from api.schemas.user import Role
from api.services.auth_service import get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> UserORM:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невалидный или просроченный токен") from exc
    user = await get_user_by_id(session, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или деактивирован")
    return user


async def require_admin(user: UserORM = Depends(get_current_user)) -> UserORM:
    if Role.ADMIN.value not in user.roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    return user
