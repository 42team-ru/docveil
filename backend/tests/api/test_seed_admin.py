"""Проверки явного поведения seed_admin для существующего пользователя."""

from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.fixture
def seed_admin_module() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "seed_admin.py"
    spec = importlib.util.spec_from_file_location("seed_admin_for_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_args_accepts_reset_password_flag(
    seed_admin_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed_admin.py",
            "--email",
            "admin@example.com",
            "--password",
            "new-password",
            "--reset-password",
        ],
    )

    args = seed_admin_module.parse_args()

    assert args.reset_password is True


@pytest.mark.asyncio
async def test_existing_admin_requires_explicit_password_reset(
    seed_admin_module: ModuleType, mocker: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    session = object()
    mocker.patch.object(
        seed_admin_module,
        "parse_args",
        return_value=Namespace(
            email="admin@example.com",
            password="new-password",
            full_name="Admin",
            role="admin",
            reset_password=False,
        ),
    )
    mocker.patch.object(
        seed_admin_module, "async_session_maker", return_value=_SessionContext(session)
    )
    mocker.patch.object(seed_admin_module, "email_exists", new=AsyncMock(return_value=True))
    reset_password = mocker.patch.object(seed_admin_module, "reset_password", new=AsyncMock())

    await seed_admin_module.main()

    reset_password.assert_not_awaited()
    output = capsys.readouterr().out
    assert "пароль НЕ изменён" in output
    assert "--reset-password" in output


@pytest.mark.asyncio
async def test_existing_admin_password_is_reset_with_flag(
    seed_admin_module: ModuleType, mocker: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    session = object()
    mocker.patch.object(
        seed_admin_module,
        "parse_args",
        return_value=Namespace(
            email="admin@example.com",
            password="new-password",
            full_name="Admin",
            role="admin",
            reset_password=True,
        ),
    )
    mocker.patch.object(
        seed_admin_module, "async_session_maker", return_value=_SessionContext(session)
    )
    mocker.patch.object(seed_admin_module, "email_exists", new=AsyncMock(return_value=True))
    reset_password = mocker.patch.object(
        seed_admin_module,
        "reset_password",
        new=AsyncMock(return_value=SimpleNamespace(email="admin@example.com")),
    )

    await seed_admin_module.main()

    reset_password.assert_awaited_once_with(session, "admin@example.com", "new-password")
    assert (
        "Пароль существующего администратора admin@example.com изменён" in capsys.readouterr().out
    )


def test_role_defaults_to_admin(
    seed_admin_module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без `--role` скрипт остаётся тем, чем был: заводит администратора."""
    monkeypatch.delenv("SEED_ROLE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_admin.py", "--email", "admin@example.com", "--password", "secret"],
    )

    args = seed_admin_module.parse_args()

    assert args.role == "admin"


@pytest.mark.asyncio
async def test_role_user_creates_account_without_admin_rights(
    seed_admin_module: ModuleType, mocker: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--role user` заводит демонстрационный аккаунт, а не второго админа."""
    session = object()
    mocker.patch.object(
        seed_admin_module,
        "parse_args",
        return_value=Namespace(
            email="demo@example.com",
            password="demo-password",
            full_name="Demo",
            role="user",
            reset_password=False,
        ),
    )
    mocker.patch.object(
        seed_admin_module, "async_session_maker", return_value=_SessionContext(session)
    )
    mocker.patch.object(seed_admin_module, "email_exists", new=AsyncMock(return_value=False))
    create_user = mocker.patch.object(
        seed_admin_module,
        "create_user",
        new=AsyncMock(return_value=SimpleNamespace(email="demo@example.com", id="uuid")),
    )

    await seed_admin_module.main()

    payload = create_user.await_args.args[1]
    assert payload.roles == [seed_admin_module.Role.USER]
    assert "с ролью user" in capsys.readouterr().out
