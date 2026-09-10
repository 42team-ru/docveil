"""Создать первого администратора напрямую в БД.

Нужен, потому что POST /users сам требует уже авторизованного админа —
взять первого пользователя иначе неоткуда.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.core.db import async_session_maker
from api.schemas.user import Role, UserCreate
from api.services.user_service import create_user, email_exists, reset_password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    parser.add_argument("--full-name", default=os.environ.get("ADMIN_FULL_NAME", "Admin"))
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="сменить пароль, если пользователь с этим email уже существует",
    )
    args = parser.parse_args()
    if not args.email or not args.password:
        parser.error("нужны --email и --password (или ADMIN_EMAIL/ADMIN_PASSWORD в .env)")
    return args


async def main() -> None:
    args = parse_args()
    async with async_session_maker() as session:
        if await email_exists(session, args.email):
            if not args.reset_password:
                print(
                    f"Пользователь {args.email} уже существует: пароль НЕ изменён. "
                    "Чтобы сменить его, повторите команду с --reset-password."
                )
                return
            user = await reset_password(session, args.email, args.password)
            if user is None:
                raise RuntimeError(f"Пользователь {args.email} исчез во время смены пароля")
            print(f"Пароль существующего администратора {user.email} изменён.")
            return
        payload = UserCreate(
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            roles=[Role.ADMIN],
        )
        user = await create_user(session, payload)
        print(f"Создан администратор {user.email} (id={user.id}).")


if __name__ == "__main__":
    asyncio.run(main())
