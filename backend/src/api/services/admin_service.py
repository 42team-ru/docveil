"""Агрегаты для админ-раздела — только чтение, только `require_admin`.

Все функции читают полные таблицы `users`/`runs`/`refresh_tokens` и считают
агрегаты в Python, а не в SQL (`GROUP BY`, `date_trunc`, фильтры по `ARRAY`/
`JSONB`). Для ожидаемого размера этой системы (сотни-тысячи строк, не
миллионы) это проще и переносимее между Postgres (прод) и sqlite (тесты —
см. комментарий про переносимые типы в `api/models/run.py`), чем дублировать
диалект-специфичный SQL. Как и `run_service.list_runs`, здесь нет предметной
логики — только форма уже сохранённых сервисами `run_service`/`user_service`
данных.
"""

from __future__ import annotations

import statistics
import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.refresh_token import RefreshTokenORM
from api.models.run import RunORM
from api.models.user import UserORM
from api.schemas.admin import (
    AdminFailureOut,
    AdminOptionsStatsOut,
    AdminRunRowOut,
    AdminRunsStatsOut,
    AdminSessionsOut,
    AdminUserRowOut,
    AdminUsersStatsOut,
    DayCountOut,
)
from api.schemas.run import RunDocument

#: Статусы прогона, которые ещё не дошли до конца (см. `RunStatus`
#: в `api/schemas/run.py`).
_IN_PROGRESS_STATUSES = ("queued", "running", "awaiting_answers", "awaiting_review")
#: Статусы, засчитывающиеся как «прогон завершился» — для доли успеха.
_FINISHED_STATUSES = ("done", "failed", "leaked")


def _as_utc(value: datetime) -> datetime:
    """sqlite (тесты) хранит `datetime` naive; Postgres (прод) — aware.
    Сравнивать разнородные значения нельзя, поэтому naive считаем UTC —
    так их и пишет `run_service`/`user_service` (`datetime.now(UTC)`)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _window_start(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _count_by(values: Iterable[str]) -> dict[str, int]:
    return dict(Counter(values))


def _daily_series(moments: Iterable[datetime], *, days: int) -> list[DayCountOut]:
    """Непрерывный ряд по дням окна, с нулями там, где событий не было —
    чартам на фронте нужна сплошная линия, а не только дни с данными."""
    counts: Counter[date] = Counter(_as_utc(moment).date() for moment in moments)
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    series: list[DayCountOut] = []
    day = start
    while day <= today:
        series.append(DayCountOut(date=day, count=counts.get(day, 0)))
        day += timedelta(days=1)
    return series


async def _all_users(session: AsyncSession) -> list[UserORM]:
    rows = await session.execute(select(UserORM))
    return list(rows.scalars())


async def _all_runs(session: AsyncSession) -> list[RunORM]:
    rows = await session.execute(select(RunORM))
    return list(rows.scalars())


async def _all_refresh_tokens(session: AsyncSession) -> list[RefreshTokenORM]:
    rows = await session.execute(select(RefreshTokenORM))
    return list(rows.scalars())


async def users_stats(session: AsyncSession, *, days: int) -> AdminUsersStatsOut:
    users = await _all_users(session)
    now = datetime.now(UTC)
    window_7d = now - timedelta(days=7)
    window_30d = now - timedelta(days=30)
    window_start = _window_start(days)

    active = sum(1 for user in users if user.is_active)
    signups = [user.created_at for user in users if _as_utc(user.created_at) >= window_start]

    return AdminUsersStatsOut(
        total=len(users),
        active=active,
        inactive=len(users) - active,
        admins=sum(1 for user in users if "admin" in user.roles),
        never_logged_in=sum(1 for user in users if user.last_login_at is None),
        active_last_7d=sum(
            1 for user in users if user.last_login_at and _as_utc(user.last_login_at) >= window_7d
        ),
        active_last_30d=sum(
            1
            for user in users
            if user.last_login_at and _as_utc(user.last_login_at) >= window_30d
        ),
        with_avatar=sum(1 for user in users if user.has_avatar),
        signups_by_day=_daily_series(signups, days=days),
    )


async def runs_stats(session: AsyncSession, *, days: int) -> AdminRunsStatsOut:
    runs = await _all_runs(session)
    window_start = _window_start(days)
    windowed = [run for run in runs if _as_utc(run.created_at) >= window_start]

    by_status = _count_by(run.status for run in runs)
    succeeded = by_status.get("done", 0)
    failed = by_status.get("failed", 0)
    leaked = by_status.get("leaked", 0)
    finished_total = succeeded + failed + leaked

    durations = [
        (_as_utc(run.finished_at) - _as_utc(run.created_at)).total_seconds()
        for run in runs
        if run.finished_at is not None and run.status in ("done", "leaked")
    ]

    return AdminRunsStatsOut(
        total=len(runs),
        by_status=by_status,
        by_format=_count_by(run.document_format for run in runs),
        by_day=_daily_series((run.created_at for run in windowed), days=days),
        succeeded=succeeded,
        failed=failed,
        leaked=leaked,
        in_progress=sum(by_status.get(status, 0) for status in _IN_PROGRESS_STATUSES),
        success_rate=(succeeded / finished_total) if finished_total else None,
        avg_duration_seconds=statistics.fmean(durations) if durations else None,
        median_duration_seconds=statistics.median(durations) if durations else None,
    )


async def options_stats(session: AsyncSession, *, days: int) -> AdminOptionsStatsOut:
    runs = await _all_runs(session)
    window_start = _window_start(days)
    windowed = [run for run in runs if _as_utc(run.created_at) >= window_start]

    mask_styles: Counter[str] = Counter()
    profile_enabled = rules_only = unmask_critical = review = with_custom_types = 0
    for run in windowed:
        options = run.options if isinstance(run.options, dict) else {}
        mask_style = options.get("mask_style")
        if isinstance(mask_style, str):
            mask_styles[mask_style] += 1
        if options.get("profile"):
            profile_enabled += 1
        if options.get("rules_only"):
            rules_only += 1
        if options.get("unmask_critical"):
            unmask_critical += 1
        if options.get("review"):
            review += 1
        if options.get("custom_types"):
            with_custom_types += 1

    return AdminOptionsStatsOut(
        by_mask_style=dict(mask_styles),
        profile_enabled=profile_enabled,
        rules_only=rules_only,
        unmask_critical=unmask_critical,
        review=review,
        with_custom_types=with_custom_types,
    )


async def failure_breakdown(
    session: AsyncSession, *, days: int, limit: int = 10
) -> list[AdminFailureOut]:
    """Топ узлов графа, роняющих прогоны, за окно `days` — самые частые
    первыми, чтобы на экране сразу было видно, где чаще всего ломается."""
    runs = await _all_runs(session)
    window_start = _window_start(days)
    failed = [
        run
        for run in runs
        if run.status == "failed" and _as_utc(run.created_at) >= window_start
    ]

    by_node: dict[str | None, list[RunORM]] = {}
    for run in failed:
        by_node.setdefault(run.node_hint, []).append(run)

    rows = [
        AdminFailureOut(
            node_hint=node_hint,
            count=len(node_runs),
            last_error=max(node_runs, key=lambda run: run.created_at).error,
            last_at=max(run.created_at for run in node_runs),
        )
        for node_hint, node_runs in by_node.items()
    ]
    rows.sort(key=lambda row: row.count, reverse=True)
    return rows[:limit]


async def sessions_stats(session: AsyncSession) -> AdminSessionsOut:
    tokens = await _all_refresh_tokens(session)
    now = datetime.now(UTC)

    active = revoked = expired = 0
    by_device: Counter[str] = Counter()
    for token in tokens:
        if token.revoked_at is not None:
            revoked += 1
        elif _as_utc(token.expires_at) <= now:
            expired += 1
        else:
            active += 1
            by_device[token.device] += 1

    return AdminSessionsOut(
        active=active,
        by_device=dict(by_device),
        revoked=revoked,
        expired=expired,
    )


async def user_rows(session: AsyncSession) -> list[AdminUserRowOut]:
    """Пользователи с их активностью — по одному проходу runs/tokens в Python,
    а не `JOIN`+`GROUP BY`: `runs.user_id` не имеет внешнего ключа (комментарий
    в `api/models/run.py`), и прогон удалённого пользователя не должен
    приписаться к чужой строке через случайное совпадение агрегата."""
    users = await _all_users(session)
    runs = await _all_runs(session)
    tokens = await _all_refresh_tokens(session)
    now = datetime.now(UTC)

    runs_total: Counter[uuid.UUID] = Counter()
    runs_failed: Counter[uuid.UUID] = Counter()
    last_run_at: dict[uuid.UUID, datetime] = {}
    for run in runs:
        runs_total[run.user_id] += 1
        if run.status == "failed":
            runs_failed[run.user_id] += 1
        previous = last_run_at.get(run.user_id)
        if previous is None or run.created_at > previous:
            last_run_at[run.user_id] = run.created_at

    active_sessions: Counter[uuid.UUID] = Counter()
    for token in tokens:
        if token.revoked_at is None and _as_utc(token.expires_at) > now:
            active_sessions[token.user_id] += 1

    return [
        AdminUserRowOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            roles=list(user.roles),
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            timezone=user.timezone,
            has_avatar=user.has_avatar,
            runs_total=runs_total.get(user.id, 0),
            runs_failed=runs_failed.get(user.id, 0),
            last_run_at=last_run_at.get(user.id),
            active_sessions=active_sessions.get(user.id, 0),
        )
        for user in users
    ]


async def list_runs_all(
    session: AsyncSession,
    *,
    query: str | None = None,
    status: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AdminRunRowOut], int]:
    """Журнал прогонов **всех** пользователей — отдельная функция от
    `run_service.list_runs`, а не флаг «показать чужое» в ней: параметр,
    снимающий фильтр по владельцу, в функции пользовательского журнала — та
    самая ошибка, из-за которой такие утечки данных и случаются."""
    users_by_id = {user.id: user for user in await _all_users(session)}
    runs = await _all_runs(session)

    filtered = runs
    if user_id is not None:
        filtered = [run for run in filtered if run.user_id == user_id]
    if status is not None:
        filtered = [run for run in filtered if run.status == status]
    if query:
        needle = query.lower()
        filtered = [run for run in filtered if needle in run.document_name.lower()]

    filtered.sort(key=lambda run: run.created_at, reverse=True)
    total = len(filtered)
    page = filtered[offset : offset + limit]

    rows = [
        AdminRunRowOut(
            id=run.id,
            status=run.status,  # type: ignore[arg-type]
            document=RunDocument(
                name=run.document_name, format=run.document_format, object_name=run.object_name
            ),
            created_at=run.created_at,
            finished_at=run.finished_at,
            node_hint=run.node_hint,
            error=run.error,
            user_id=run.user_id,
            user_email=users_by_id[run.user_id].email if run.user_id in users_by_id else None,
            user_full_name=(
                users_by_id[run.user_id].full_name if run.user_id in users_by_id else None
            ),
        )
        for run in page
    ]
    return rows, total
