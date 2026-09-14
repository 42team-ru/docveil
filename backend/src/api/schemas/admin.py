"""Схемы админ-раздела — агрегаты по системе, доступные только `require_admin`.

Ничего здесь не хранится отдельно: все поля — либо агрегаты над `users`/`runs`/
`refresh_tokens` (`api/services/admin_service.py`), либо переиспользованные
формы `UserPublic`/`RunDocument`/`RunStatus`. Токены/стоимость LLM сюда
намеренно не попадают — это состояние живёт только внутри `report.json`
конкретного прогона в чекпойнтере графа, кросс-прогонного роллапа в Postgres
нет и подделывать его агрегатом отсюда нельзя.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from api.schemas.run import RunDocument, RunStatus
from api.schemas.user import Role


class DayCountOut(BaseModel):
    """Одна точка временного ряда «событий за день»."""

    date: date
    count: int


class AdminUsersStatsOut(BaseModel):
    """Сводка по таблице `users`."""

    total: int
    active: int
    inactive: int
    admins: int
    never_logged_in: int
    active_last_7d: int
    active_last_30d: int
    with_avatar: int
    signups_by_day: list[DayCountOut] = Field(default_factory=list)


class AdminRunsStatsOut(BaseModel):
    """Сводка по таблице `runs` за окно `days` (см. `AdminOverviewOut.window_days`)."""

    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_format: dict[str, int] = Field(default_factory=dict)
    by_day: list[DayCountOut] = Field(default_factory=list)
    succeeded: int
    failed: int
    leaked: int
    in_progress: int
    #: Доля `succeeded` среди завершённых (`succeeded + failed + leaked`);
    #: `None`, если завершённых прогонов ещё не было — делить не на что.
    success_rate: float | None = None
    avg_duration_seconds: float | None = None
    median_duration_seconds: float | None = None


class AdminOptionsStatsOut(BaseModel):
    """Разбор `RunORM.options` (JSONB тела `RunCreateRequest`) за окно `days`.

    `mask_style` — единственное поле опций с более чем двумя значениями
    (`marker`/`blackbox`/`both`), поэтому только оно — распределение; прочие
    булевы флаги — просто счётчик прогонов, где флаг включён.
    """

    by_mask_style: dict[str, int] = Field(default_factory=dict)
    profile_enabled: int
    rules_only: int
    unmask_critical: int
    review: int
    with_custom_types: int


class AdminFailureOut(BaseModel):
    """Строка топа падающих узлов графа — где именно система ломается чаще всего."""

    node_hint: str | None
    count: int
    last_error: str | None
    last_at: datetime | None


class AdminSessionsOut(BaseModel):
    """Сводка по `refresh_tokens` — активные сессии/устройства прямо сейчас."""

    active: int
    by_device: dict[str, int] = Field(default_factory=dict)
    revoked: int
    expired: int


class AdminUserRowOut(BaseModel):
    """Строка таблицы пользователей в админке — профиль плюс его активность."""

    id: uuid.UUID
    email: str
    full_name: str
    roles: list[Role]
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None
    timezone: str | None = None
    has_avatar: bool = False
    runs_total: int = 0
    runs_failed: int = 0
    last_run_at: datetime | None = None
    active_sessions: int = 0


class AdminRunRowOut(BaseModel):
    """Строка журнала прогонов всех пользователей (в отличие от `RunListItem` —
    журнала одного пользователя)."""

    id: uuid.UUID
    status: RunStatus
    document: RunDocument
    created_at: datetime
    finished_at: datetime | None = None
    node_hint: str | None = None
    error: str | None = None
    user_id: uuid.UUID
    user_email: str | None = None
    user_full_name: str | None = None


class AdminRunListResponse(BaseModel):
    items: list[AdminRunRowOut]
    total: int


class AdminOverviewOut(BaseModel):
    """Единый ответ `GET /admin/overview` — всё для сводного экрана одним запросом."""

    generated_at: datetime
    window_days: int
    users: AdminUsersStatsOut
    runs: AdminRunsStatsOut
    options: AdminOptionsStatsOut
    failures: list[AdminFailureOut] = Field(default_factory=list)
    sessions: AdminSessionsOut
    top_users: list[AdminUserRowOut] = Field(default_factory=list)
