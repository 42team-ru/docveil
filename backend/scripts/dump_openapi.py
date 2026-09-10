"""Выгрузить OpenAPI-схему FastAPI-приложения в снимок для Orval.

Фронт (`orval.config.ts`) без `ORVAL_BACKEND_ENV` берёт схему не у живого
бэкенда, а из закоммиченного `frontend/src/shared/api/schemas/core.json` —
чтобы `yarn orval`/`yarn typecheck`/`yarn test` не требовали поднятого
бэкенда. Этот скрипт и есть единственный способ обновить снимок вручную,
без докера и живого сервера: `app.openapi()` строит схему в процессе, без
поднятия uvicorn.

Запуск (из `backend/`):

    .venv/Scripts/python scripts/dump_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

#: Снимок читает фронт — путь фиксирован тем же соглашением, что и
#: `output.target` в `orval.config.ts`.
SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "shared"
    / "api"
    / "schemas"
    / "core.json"
)


def main() -> int:
    from api.main import app

    schema = app.openapi()
    SNAPSHOT_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"снимок обновлён: {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
