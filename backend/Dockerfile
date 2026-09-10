# syntax=docker/dockerfile:1
#
# Рантайм-образ веб-слоя (FastAPI + пайплайн обезличивания).
# Тесты, фикстуры и spikes в образ не кладём — см. .dockerignore.

FROM python:3.13-slim AS runtime

# Контекст сборки — backend/, поэтому корневой .git намеренно в него не попадает.
# Релизный workflow передаёт сюда версию, вычисленную из тега и истории коммитов.
ARG DOCVEIL_VERSION

# tesseract — внешний бинарь для pytesseract (OCR сканов) с русским пакетом.
# libgl/libglib — рантайм PyMuPDF при рендере страниц.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-rus \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# uv устанавливается через pip: не нужна аутентификация в ghcr.io.
RUN pip install --no-cache-dir "uv==0.12.12"

# Образ ставит tesseract-ocr системным пакетом (выше) — значит и объявляет
# его. Без этой строки выигрывает `provider: fake` из `masker.yaml`, который
# приезжает вместе с исходниками: в репозитории он стоит намеренно, чтобы
# ворота были воспроизводимы на машине без tesseract. В продукте же это
# означало бы, что сканы молча не распознаются при установленном движке —
# проверено на собранном образе 10.09.2026, `select_ocr()` возвращал FakeOCR.
ENV MASKER_OCR=tesseract

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    SETUPTOOLS_SCM_PRETEND_VERSION=${DOCVEIL_VERSION} \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Слой зависимостей кешируется отдельно от исходников: меняется реже.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Порт по умолчанию совпадает с дефолтом Settings.app_port (src/api/core/config.py);
# переопределяется переменной окружения APP_PORT (см. .env.example).
EXPOSE 8000

# Перед стартом накатываем миграции (DATABASE_URL берётся из окружения).
CMD ["sh", "-c", "alembic upgrade head && uvicorn api.main:app --app-dir src --host 0.0.0.0 --port ${APP_PORT:-8000}"]
