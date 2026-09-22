"""Роуты админ-раздела — сводная аналитика по системе (только для админов).

Тонкая обёртка над `api.services.admin_service`, как `routers/users.py` —
никакой предметной логики здесь, только вызов сервиса и коды ответа.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.db import get_db
from api.core.deps import require_admin
from api.schemas.admin import AdminOverviewOut, AdminRunListResponse, AdminUserRowOut
from api.services.admin_service import (
    failure_breakdown,
    list_runs_all,
    options_stats,
    runs_stats,
    sessions_stats,
    user_rows,
    users_stats,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/overview", response_model=AdminOverviewOut)
async def get_overview(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_db),
) -> AdminOverviewOut:
    users = await users_stats(session, days=days)
    runs = await runs_stats(session, days=days)
    options = await options_stats(session, days=days)
    failures = await failure_breakdown(session, days=days)
    sessions = await sessions_stats(session)
    top_users = sorted(await user_rows(session), key=lambda row: row.runs_total, reverse=True)[:10]

    return AdminOverviewOut(
        generated_at=datetime.now(UTC),
        window_days=days,
        users=users,
        runs=runs,
        options=options,
        failures=failures,
        sessions=sessions,
        top_users=top_users,
    )


@router.get("/users", response_model=list[AdminUserRowOut])
async def get_users(session: AsyncSession = Depends(get_db)) -> list[AdminUserRowOut]:
    return await user_rows(session)


@router.get("/runs", response_model=AdminRunListResponse)
async def get_runs(
    query: str | None = None,
    status: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> AdminRunListResponse:
    items, total = await list_runs_all(
        session, query=query, status=status, user_id=user_id, limit=limit, offset=offset
    )
    return AdminRunListResponse(items=items, total=total)
