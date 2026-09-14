"""Юнит-тесты api.services.admin_service — агрегация уже загруженных строк.

`UserORM.roles` (`ARRAY(String)`) и `RefreshTokenORM` (постгресовые `UUID`/
`TIMESTAMP`) не переносимы на sqlite — в отличие от `RunORM`, они не были
рассчитаны на тесты без живого Postgres (см. `test_user_service.py`, где по
той же причине сессия мокается, а не поднимается в sqlite). Поэтому здесь
мокаются не SQL-запросы, а сами точки чтения таблиц целиком (`_all_users`,
`_all_runs`, `_all_refresh_tokens`) — они и так лишь `select(...)` без
фильтров, вся проверяемая логика начинается после них.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from api.models.refresh_token import RefreshTokenORM
from api.models.run import RunORM
from api.models.user import UserORM
from api.services.admin_service import (
    failure_breakdown,
    list_runs_all,
    options_stats,
    runs_stats,
    sessions_stats,
    user_rows,
    users_stats,
)

NOW = datetime.now(UTC)


def _user(
    *,
    roles: list[str] | None = None,
    is_active: bool = True,
    last_login_at: datetime | None = None,
    created_at: datetime | None = None,
    avatar: str | None = None,
) -> UserORM:
    return UserORM(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="hash",
        full_name="Some User",
        roles=roles or ["user"],
        is_active=is_active,
        created_at=created_at or NOW,
        last_login_at=last_login_at,
        avatar_object_name=avatar,
    )


def _run(
    *,
    user_id: uuid.UUID,
    status: str = "done",
    document_format: str = "pdf",
    created_at: datetime | None = None,
    finished_at: datetime | None = None,
    node_hint: str | None = None,
    error: str | None = None,
    options: dict | None = None,
    document_name: str = "document.pdf",
) -> RunORM:
    return RunORM(
        id=uuid.uuid4(),
        user_id=user_id,
        thread_id=uuid.uuid4().hex,
        object_name="documents/document.pdf",
        document_name=document_name,
        document_format=document_format,
        options=options or {"mask_style": "marker"},
        status=status,
        node_hint=node_hint,
        error=error,
        created_at=created_at or NOW,
        finished_at=finished_at,
    )


def _token(
    *,
    user_id: uuid.UUID,
    device: str = "web",
    expires_at: datetime,
    revoked_at: datetime | None = None,
) -> RefreshTokenORM:
    return RefreshTokenORM(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=uuid.uuid4().hex,
        device=device,
        created_at=NOW,
        expires_at=expires_at,
        revoked_at=revoked_at,
    )


def _mock_tables(mocker, *, users=(), runs=(), tokens=()) -> None:
    mocker.patch(
        "api.services.admin_service._all_users", AsyncMock(return_value=list(users))
    )
    mocker.patch(
        "api.services.admin_service._all_runs", AsyncMock(return_value=list(runs))
    )
    mocker.patch(
        "api.services.admin_service._all_refresh_tokens",
        AsyncMock(return_value=list(tokens)),
    )


@pytest.mark.asyncio
async def test_users_stats_counts_and_windows(mocker):
    stale_admin = _user(
        roles=["admin"], last_login_at=NOW - timedelta(days=40), created_at=NOW - timedelta(days=60)
    )
    recent_user = _user(last_login_at=NOW - timedelta(days=1), created_at=NOW - timedelta(days=1))
    inactive_never_logged_in = _user(is_active=False, avatar="avatar.png")
    _mock_tables(mocker, users=[stale_admin, recent_user, inactive_never_logged_in])

    stats = await users_stats(object(), days=30)

    assert stats.total == 3
    assert stats.active == 2
    assert stats.inactive == 1
    assert stats.admins == 1
    assert stats.never_logged_in == 1
    assert stats.active_last_7d == 1
    assert stats.active_last_30d == 1
    assert stats.with_avatar == 1
    # Окно 30 дней: только recent_user и inactive_never_logged_in попадают в ряд регистраций.
    assert sum(day.count for day in stats.signups_by_day) == 2
    assert len(stats.signups_by_day) == 30


@pytest.mark.asyncio
async def test_users_stats_empty_table_has_no_division_errors(mocker):
    _mock_tables(mocker)

    stats = await users_stats(object(), days=7)

    assert stats.total == 0
    assert stats.active_last_7d == 0
    assert len(stats.signups_by_day) == 7


@pytest.mark.asyncio
async def test_runs_stats_success_rate_and_durations(mocker):
    owner = uuid.uuid4()
    done = _run(
        user_id=owner,
        status="done",
        created_at=NOW - timedelta(minutes=10),
        finished_at=NOW - timedelta(minutes=9),
    )
    failed = _run(user_id=owner, status="failed", node_hint="render")
    running = _run(user_id=owner, status="running")
    _mock_tables(mocker, runs=[done, failed, running])

    stats = await runs_stats(object(), days=30)

    assert stats.total == 3
    assert stats.succeeded == 1
    assert stats.failed == 1
    assert stats.in_progress == 1
    assert stats.success_rate == pytest.approx(0.5)
    assert stats.avg_duration_seconds == pytest.approx(60.0)
    assert stats.median_duration_seconds == pytest.approx(60.0)
    assert stats.by_format == {"pdf": 3}


@pytest.mark.asyncio
async def test_runs_stats_no_finished_runs_gives_none_rate(mocker):
    _mock_tables(mocker, runs=[_run(user_id=uuid.uuid4(), status="queued")])

    stats = await runs_stats(object(), days=30)

    assert stats.success_rate is None
    assert stats.avg_duration_seconds is None
    assert stats.median_duration_seconds is None


@pytest.mark.asyncio
async def test_options_stats_breaks_down_mask_style_and_flags(mocker):
    owner = uuid.uuid4()
    _mock_tables(
        mocker,
        runs=[
            _run(
                user_id=owner,
                options={
                    "mask_style": "marker",
                    "profile": True,
                    "rules_only": False,
                    "unmask_critical": False,
                    "review": True,
                    "custom_types": [{"id": "x"}],
                },
            ),
            _run(
                user_id=owner,
                options={
                    "mask_style": "blackbox",
                    "profile": False,
                    "rules_only": True,
                    "unmask_critical": True,
                    "review": False,
                    "custom_types": [],
                },
            ),
        ],
    )

    stats = await options_stats(object(), days=30)

    assert stats.by_mask_style == {"marker": 1, "blackbox": 1}
    assert stats.profile_enabled == 1
    assert stats.rules_only == 1
    assert stats.unmask_critical == 1
    assert stats.review == 1
    assert stats.with_custom_types == 1


@pytest.mark.asyncio
async def test_failure_breakdown_orders_by_count_desc(mocker):
    owner = uuid.uuid4()
    _mock_tables(
        mocker,
        runs=[
            _run(user_id=owner, status="failed", node_hint="render", error="e1"),
            _run(user_id=owner, status="failed", node_hint="render", error="e2"),
            _run(user_id=owner, status="failed", node_hint="ocr", error="e3"),
            _run(user_id=owner, status="done"),
        ],
    )

    rows = await failure_breakdown(object(), days=30)

    assert rows[0].node_hint == "render"
    assert rows[0].count == 2
    assert rows[1].node_hint == "ocr"
    assert rows[1].count == 1


@pytest.mark.asyncio
async def test_sessions_stats_splits_active_revoked_expired(mocker):
    owner = uuid.uuid4()
    active = _token(user_id=owner, device="web", expires_at=NOW + timedelta(days=1))
    revoked = _token(
        user_id=owner, device="web", expires_at=NOW + timedelta(days=1), revoked_at=NOW
    )
    expired = _token(user_id=owner, device="mobile", expires_at=NOW - timedelta(days=1))
    _mock_tables(mocker, tokens=[active, revoked, expired])

    stats = await sessions_stats(object())

    assert stats.active == 1
    assert stats.revoked == 1
    assert stats.expired == 1
    assert stats.by_device == {"web": 1}


@pytest.mark.asyncio
async def test_user_rows_aggregates_runs_and_sessions_without_fk(mocker):
    user = _user()
    orphan_run_owner = uuid.uuid4()  # прогон без соответствующей строки users
    _mock_tables(
        mocker,
        users=[user],
        runs=[
            _run(user_id=user.id, status="done"),
            _run(user_id=user.id, status="failed"),
            _run(user_id=orphan_run_owner, status="done"),
        ],
    )

    rows = await user_rows(object())

    assert len(rows) == 1  # прогон orphan_run_owner не создал лишнюю строку
    row = rows[0]
    assert row.id == user.id
    assert row.runs_total == 2
    assert row.runs_failed == 1


@pytest.mark.asyncio
async def test_list_runs_all_filters_and_paginates_across_owners(mocker):
    alice = _user()
    bob = _user()
    _mock_tables(
        mocker,
        users=[alice, bob],
        runs=[
            _run(user_id=alice.id, status="done", document_name="contract.pdf"),
            _run(user_id=bob.id, status="failed", document_name="invoice.pdf"),
            _run(user_id=bob.id, status="done", document_name="report.pdf"),
        ],
    )

    all_rows, total = await list_runs_all(object(), limit=50, offset=0)
    assert total == 3
    assert len(all_rows) == 3

    only_bob, total_bob = await list_runs_all(object(), user_id=bob.id, limit=50, offset=0)
    assert total_bob == 2
    assert all(row.user_id == bob.id for row in only_bob)

    only_failed, total_failed = await list_runs_all(object(), status="failed", limit=50, offset=0)
    assert total_failed == 1
    assert only_failed[0].document.name == "invoice.pdf"

    by_query, total_query = await list_runs_all(object(), query="contract", limit=50, offset=0)
    assert total_query == 1
    assert by_query[0].user_email == alice.email

    page, total_page = await list_runs_all(object(), limit=1, offset=1)
    assert total_page == 3
    assert len(page) == 1
