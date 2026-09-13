"""Проверка живости сервиса для оркестратора контейнеров и балансировщика.

Отдельный роутер, а не строка в ``main.py``: healthcheck обязан быть
доступен без авторизации и без обращения к БД, поэтому он не должен
случайно уехать под общую зависимость роутеров бизнес-логики.

Проверка намеренно поверхностная: она отвечает на вопрос «процесс поднялся
и обслуживает HTTP», а не «Postgres и MinIO живы». Глубокая проверка в
healthcheck контейнера означала бы перезапуск рабочего бэкенда из-за
недоступной чужой зависимости — лечение, которое хуже болезни.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthOut(BaseModel):
    """Ответ проверки живости."""

    status: str


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    """Ответить, что процесс поднят и обслуживает запросы."""
    return HealthOut(status="ok")
