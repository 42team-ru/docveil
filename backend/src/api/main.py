"""Точка входа FastAPI-приложения веб-слоя."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.concurrency import run_in_threadpool

from api.core.storage import ensure_bucket
from api.routers import auth, files, users


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    await run_in_threadpool(ensure_bucket)
    yield


app = FastAPI(title="Triema Masker API", lifespan=lifespan)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
app.include_router(api_router)
