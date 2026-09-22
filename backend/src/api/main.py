"""Точка входа FastAPI-приложения веб-слоя."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from api.core.config import settings
from api.core.logging import configure_logging, request_id_var
from api.core.storage import ensure_bucket
from api.core.warmup import warm_up
from api.routers import admin, auth, custom_types, files, health, llm_profiles, ocr, runs, users
from api.services import run_service

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await run_in_threadpool(ensure_bucket)
    await run_service.cleanup_stale_runs()
    # Прогрев выключен по умолчанию: тесты и локальный `make api` не должны
    # платить за загрузку Natasha на каждом старте. На стенде включается
    # переменной WARMUP_ON_START (см. docker-compose.prod.yml).
    if settings.warmup_on_start:
        await run_in_threadpool(warm_up)
    yield


app = FastAPI(title="Triema Masker API", lifespan=lifespan)

# Фронт живёт на своём источнике (дев-сервер Vite на 5173, прод — свой домен),
# поэтому браузеру нужно разрешение. `allow_credentials` обязателен: без него
# не уедет httpOnly-cookie с refresh-токеном, и сессия не переживёт
# перезагрузку вкладки. `Content-Disposition` выставлен наружу явно — иначе
# скрипт страницы не увидит имя файла у скачиваемого артефакта.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-Id"],
)


@app.middleware("http")
async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Один ID на весь запрос — сшивает строки лога одного запроса, включая
    необработанное исключение, залогированное здесь же.

    Раньше необработанное исключение уходило только в дефолтный traceback
    uvicorn без контекста запроса — 500 у пользователя было невозможно
    объяснить по логам (см. AGENTS.md, «очень слабое логирование»).
    `HTTPException` (401/403/404/422 и т.п.) сюда не попадает — её уже
    превращает в ответ обработчик Starlette внутри `call_next`, до того как
    исключение способно всплыть сюда.

    Лог и генерик-500 собраны прямо в `except`, а не через
    `@app.exception_handler(Exception)`: у `BaseHTTPMiddleware` (на нём
    построен `@app.middleware("http")`) есть задокументированный конфликт с
    хендлерами общего `Exception` — ответ, который такой хендлер строит
    глубже в стеке, до `call_next` не долетает, и наружу всё равно уходит
    голое исключение вместо ответа.
    """
    request_id = uuid.uuid4().hex
    token = request_id_var.set(request_id)
    try:
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "Необработанное исключение: %s %s", request.method, request.url.path, exc_info=exc
            )
            response = JSONResponse(
                status_code=500, content={"detail": "Внутренняя ошибка сервера"}
            )
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response


api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(custom_types.router)
api_router.include_router(ocr.router)
api_router.include_router(runs.router)
api_router.include_router(admin.router)
api_router.include_router(llm_profiles.router)
app.include_router(api_router)


def custom_openapi() -> dict[str, Any]:
    """Схема отдаёт пути без `/api` — Orval строит из них клиент, а базовый URL
    (с `/api`) уже добавляет фронтовый `authMutator`. Реальные маршруты
    (`api_router`, выше) от этого не меняются — `servers` ниже возвращает
    `/api` обратно для Swagger UI («Try it out» бьёт по настоящим путям).
    """
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schema["paths"] = {
        path.removeprefix("/api") or "/": path_item for path, path_item in schema["paths"].items()
    }
    schema["servers"] = [{"url": "/api"}]

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[method-assign]
