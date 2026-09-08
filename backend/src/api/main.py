"""Точка входа FastAPI-приложения веб-слоя."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from api.core.config import settings
from api.core.storage import ensure_bucket
from api.routers import auth, custom_types, files, runs, users


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
api_router.include_router(runs.router)
app.include_router(api_router)
