"""Роуты управления пользователями (только для администраторов)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.db import get_db
from api.core.deps import require_admin
from api.models.user import UserORM
from api.schemas.user import UserCreate, UserPublic
from api.services.user_service import create_user, email_exists, list_users

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: UserCreate,
    session: AsyncSession = Depends(get_db),
) -> UserORM:
    if await email_exists(session, payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким email уже существует")
    return await create_user(session, payload)


@router.get("", response_model=list[UserPublic])
async def list_users_endpoint(session: AsyncSession = Depends(get_db)) -> list[UserORM]:
    return await list_users(session)
