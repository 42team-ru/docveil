"""Роуты настроек LLM-профиля (только для администраторов)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.db import get_db
from api.core.deps import require_admin
from api.schemas.llm_profile import (
    LLMActivateRequest,
    LLMProfileCreate,
    LLMProfileOut,
    LLMProfileUpdate,
)
from api.services import llm_profile_service

router = APIRouter(
    prefix="/admin/llm-profiles", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("", response_model=list[LLMProfileOut])
async def list_llm_profiles_endpoint(
    session: AsyncSession = Depends(get_db),
) -> list[LLMProfileOut]:
    return await llm_profile_service.list_profiles(session)


@router.post("", response_model=LLMProfileOut, status_code=status.HTTP_201_CREATED)
async def create_llm_profile_endpoint(
    payload: LLMProfileCreate,
    session: AsyncSession = Depends(get_db),
) -> LLMProfileOut:
    return await llm_profile_service.create_profile(session, payload)


@router.patch("/{profile_id}", response_model=LLMProfileOut)
async def update_llm_profile_endpoint(
    profile_id: uuid.UUID,
    payload: LLMProfileUpdate,
    session: AsyncSession = Depends(get_db),
) -> LLMProfileOut:
    return await llm_profile_service.update_profile(session, profile_id, payload)


@router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_llm_profile_endpoint(
    profile_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    await llm_profile_service.delete_profile(session, profile_id)


@router.post("/activate", status_code=status.HTTP_204_NO_CONTENT)
async def activate_llm_profile_endpoint(
    payload: LLMActivateRequest,
    session: AsyncSession = Depends(get_db),
) -> None:
    await llm_profile_service.set_active(session, payload.source, payload.name)
