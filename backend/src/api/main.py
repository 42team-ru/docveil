"""Точка входа FastAPI-приложения веб-слоя."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.storage import ensure_bucket
from api.routers import auth, custom_types, files, ocr, runs, users


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await run_in_threadpool(ensure_bucket)
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
    expose_headers=["Content-Disposition"],
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(custom_types.router)
api_router.include_router(ocr.router)
api_router.include_router(runs.router)
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
