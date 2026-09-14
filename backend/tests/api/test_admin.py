import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from api.core.deps import get_current_user, require_admin
from api.main import app
from api.models.user import UserORM
from api.schemas.admin import (
    AdminFailureOut,
    AdminOptionsStatsOut,
    AdminRunRowOut,
    AdminRunsStatsOut,
    AdminSessionsOut,
    AdminUserRowOut,
    AdminUsersStatsOut,
)
from api.schemas.run import RunDocument


@pytest.fixture
def admin_user():
    return UserORM(
        id=uuid.uuid4(),
        email="admin@example.com",
        password_hash="hash",
        full_name="Admin",
        roles=["admin"],
        is_active=True,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def override_require_admin(admin_user):
    async def _mock_require_admin():
        return admin_user

    app.dependency_overrides[require_admin] = _mock_require_admin
    yield
    app.dependency_overrides.pop(require_admin, None)


@pytest.fixture
def mock_admin_service(mocker):
    mocker.patch("api.routers.admin.users_stats", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.runs_stats", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.options_stats", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.failure_breakdown", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.sessions_stats", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.user_rows", new_callable=AsyncMock)
    mocker.patch("api.routers.admin.list_runs_all", new_callable=AsyncMock)
    return mocker


def _users_stats() -> AdminUsersStatsOut:
    return AdminUsersStatsOut(
        total=3,
        active=2,
        inactive=1,
        admins=1,
        never_logged_in=1,
        active_last_7d=1,
        active_last_30d=2,
        with_avatar=0,
        signups_by_day=[],
    )


def _runs_stats() -> AdminRunsStatsOut:
    return AdminRunsStatsOut(
        total=5,
        by_status={"done": 4, "failed": 1},
        by_format={"pdf": 5},
        by_day=[],
        succeeded=4,
        failed=1,
        leaked=0,
        in_progress=0,
        success_rate=0.8,
        avg_duration_seconds=12.5,
        median_duration_seconds=10.0,
    )


def _options_stats() -> AdminOptionsStatsOut:
    return AdminOptionsStatsOut(
        by_mask_style={"marker": 5},
        profile_enabled=3,
        rules_only=0,
        unmask_critical=0,
        review=5,
        with_custom_types=1,
    )


def _user_row(admin_user: UserORM) -> AdminUserRowOut:
    return AdminUserRowOut(
        id=admin_user.id,
        email=admin_user.email,
        full_name=admin_user.full_name,
        roles=admin_user.roles,
        is_active=admin_user.is_active,
        created_at=admin_user.created_at,
        runs_total=2,
        runs_failed=0,
        active_sessions=1,
    )


def test_get_overview_success(client, override_require_admin, mock_admin_service, admin_user):
    mock_admin_service.patch("api.routers.admin.users_stats").return_value = _users_stats()
    mock_admin_service.patch("api.routers.admin.runs_stats").return_value = _runs_stats()
    mock_admin_service.patch("api.routers.admin.options_stats").return_value = _options_stats()
    mock_admin_service.patch("api.routers.admin.failure_breakdown").return_value = [
        AdminFailureOut(node_hint="render", count=1, last_error="boom", last_at=None)
    ]
    mock_admin_service.patch("api.routers.admin.sessions_stats").return_value = AdminSessionsOut(
        active=1, by_device={"web": 1}, revoked=0, expired=0
    )
    mock_admin_service.patch("api.routers.admin.user_rows").return_value = [
        _user_row(admin_user)
    ]

    response = client.get("/api/admin/overview")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["window_days"] == 30
    assert data["users"]["total"] == 3
    assert data["runs"]["succeeded"] == 4
    assert data["options"]["by_mask_style"] == {"marker": 5}
    assert data["failures"][0]["node_hint"] == "render"
    assert data["sessions"]["active"] == 1
    assert data["top_users"][0]["email"] == admin_user.email


def test_get_overview_rejects_out_of_range_days(client, override_require_admin, mock_admin_service):
    response = client.get("/api/admin/overview", params={"days": 0})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    response = client.get("/api/admin/overview", params={"days": 400})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_overview_forbidden_for_non_admin(client, mock_admin_service):
    non_admin = UserORM(
        id=uuid.uuid4(),
        email="user@example.com",
        password_hash="hash",
        full_name="Regular User",
        roles=["user"],
        is_active=True,
        created_at=datetime.now(UTC),
    )

    async def _mock_get_current_user():
        return non_admin

    app.dependency_overrides[get_current_user] = _mock_get_current_user
    try:
        response = client.get("/api/admin/overview")
        assert response.status_code == status.HTTP_403_FORBIDDEN
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_get_overview_unauthorized_without_token(client, mock_admin_service):
    response = client.get("/api/admin/overview")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_users_success(client, override_require_admin, mock_admin_service, admin_user):
    mock_admin_service.patch("api.routers.admin.user_rows").return_value = [_user_row(admin_user)]

    response = client.get("/api/admin/users")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["email"] == admin_user.email
    assert data[0]["runs_total"] == 2


def test_get_users_forbidden_for_non_admin(client, mock_admin_service):
    response = client.get("/api/admin/users")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_runs_success(client, override_require_admin, mock_admin_service, admin_user):
    row = AdminRunRowOut(
        id=uuid.uuid4(),
        status="done",
        document=RunDocument(name="doc.pdf", format="pdf", object_name="obj"),
        created_at=datetime.now(UTC),
        user_id=admin_user.id,
        user_email=admin_user.email,
        user_full_name=admin_user.full_name,
    )
    mock_admin_service.patch("api.routers.admin.list_runs_all").return_value = ([row], 1)

    response = client.get("/api/admin/runs")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["user_email"] == admin_user.email


def test_get_runs_rejects_out_of_range_limit(client, override_require_admin, mock_admin_service):
    response = client.get("/api/admin/runs", params={"limit": 0})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    response = client.get("/api/admin/runs", params={"limit": 500})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_get_runs_passes_filters_to_service(
    client, override_require_admin, mock_admin_service, admin_user
):
    list_runs_mock = mock_admin_service.patch("api.routers.admin.list_runs_all")
    list_runs_mock.return_value = ([], 0)

    response = client.get(
        "/api/admin/runs",
        params={"query": "договор", "status": "failed", "user_id": str(admin_user.id)},
    )

    assert response.status_code == status.HTTP_200_OK
    call_kwargs = list_runs_mock.call_args.kwargs
    assert call_kwargs["query"] == "договор"
    assert call_kwargs["status"] == "failed"
    assert call_kwargs["user_id"] == admin_user.id
