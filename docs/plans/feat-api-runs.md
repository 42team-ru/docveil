# План: REST API для прогонов обезличивания и OCR

## Контекст

В `TASKS.md` открыта задача В1 «REST прогонов: мост между пайплайном и вебом»
и В8 «История прогонов». API-каркас уже есть (`backend/src/api/`): FastAPI,
JWT + refresh (`api/routers/auth.py`), MinIO (`api/services/file_service.py`),
загрузка `/api/files/upload`, готовый паттерн `run_in_threadpool` +
`checkpointer_factory` в `/api/custom_types/compile[/{tid}/answers]`. CLI
уже позовёт `masker.run.start_run`/`resume_run` с чекпойнтером; веб — тот
же путь под другим вызывающим (`AGENTS.md`, требование заказчика №6).

**Решение в одном абзаце.** Добавить два роута под `/api/runs`
(старт прогона, ответы на вопросы) и один под `/api/ocr` (голый OCR без
маскировки). Файл прогона берётся из MinIO по `object_name` (как в
`/custom_types/compile`), результат выкладывается обратно в MinIO под тем
же `runs/{thread_id}/`; в ответе — presigned URL на каждый артефакт, TTL
`600` секунд. Список прогонов и полный отчёт — над отдельной SQL-таблицей
`runs` (SQLAlchemy async, миграция alembic), пишется хуком `on_finish` в
сервисе. Синхронный ответ через `run_in_threadpool` — как у compile;
прогоны длиннее 30 секунд ловим по времени и отвечаем `503` с советом
запросить фоновый режим (в MVP не реализуем). Все OCR-настройки —
серверные (yaml/env), в API нет ни `ocr_provider`, ни `ocr_dpi`, ни
`force_ocr`. Дополнительно предусмотреть в ответе на прогон поле
`highlights: []` c нужным для фронта форматом, но заполнять пустым (реальные
данные — в **feat-highlight-coords-edits**, чтобы фронт мог начать работать
с контрактом заранее).

## Ветка

```
git switch -c feat/api-runs  # от feat/ocr-scan-render
```

## Роуты (публичный контракт)

### `POST /api/runs`

Тело:
```json
{
  "object_name": "uuid/contract.pdf",
  "types": ["inn", "ogrn", "person"],            // null = все встроенные
  "interactive": true,                             // false = не паузить
  "styles": ["marker", "blackbox"],                // непусто; повторяет CLI
  "preview": true,
  "highlight_background": "#FFEE00",               // null | "#RRGGBB"
  "unmask_critical": false,
  "custom_types": [],                              // из /custom_types/compile
  "image_output_format": "original"                // от feat-image-ingest
}
```

Ответ (`status=done`):
```json
{
  "thread_id": "abcdef1234567890",
  "status": "done",
  "artifacts": [
    {"role":"masked_highlight","name":"masked_highlight.pdf","object_name":"runs/.../masked_highlight.pdf","url":"https://…?X-Amz…","expires_at":"…"}
  ],
  "report": { /* content of report.json */ },
  "highlights": []
}
```

Ответ (`status=waiting`):
```json
{
  "thread_id": "…",
  "status": "waiting",
  "questions": [ /* конверт из ask_human */ ],
  "artifacts": [],
  "report": null,
  "highlights": []
}
```

Ошибки:
- `422` — валидация тела (Pydantic).
- `422` — `NotADocumentError` из ingest_image (см. feat-image-ingest).
- `404` — object_name не найден в MinIO.
- `409` — `ThreadExistsError` (при явно заданном `thread_id`, которого в MVP нет).
- `500` → детализация `RunFailedError` c `node_hint`.

### `POST /api/runs/{thread_id}/answers`

Тело:
```json
{ "schema_version": 1, "answers": { "q1": "маскировать", "…": "…" } }
```

Ответ — та же схема, что и `POST /api/runs`.

Ошибки: `404` (unknown), `409` (already finished).

### `GET /api/runs`

Параметры: `limit=50`, `offset=0`, `status=done|waiting|failed`. Пагинация
как в `custom_types` (не реализована — берём как задел). Ответ:
```json
{
  "items": [ {"thread_id":"…","status":"done","file_name":"contract.pdf","created_at":"…","finished_at":"…"} ],
  "total": 42
}
```

### `GET /api/runs/{thread_id}`

Полный отчёт + артефакты + `highlights`. Ошибка `404` если тред не найден
ни в SQL, ни в чекпойнте.

### `POST /api/ocr/extract`

Тело: `{ "object_name": "..." }`. Ответ:
```json
{
  "pages": [
    { "page": 0, "width_pt": 595, "height_pt": 842, "dpi": 400,
      "lines": [ {"text":"…","bbox":[x0,y0,x1,y1],"polygon":[[x,y],…],"confidence":0.98,"order":0} ] }
  ],
  "provider": "tesseract"
}
```

Годится и для PDF (пер-страничный OCR **только** на скан-страницах, как в
`ingest_pdf`), и для картинок (после конвертации). Не сохраняет ничего в
БД — чистый extract.

## Раскладка изменений

| Файл | Действие |
|---|---|
| `backend/src/api/routers/runs.py` | **NEW.** Три роута выше. Паттерн полностью с `custom_types.py`. |
| `backend/src/api/routers/ocr.py` | **NEW.** `POST /api/ocr/extract`. |
| `backend/src/api/services/runs_service.py` | **NEW.** `start_masker_run`, `answer_masker_questions`, `list_runs`, `get_run` — обёртки над `masker.run.*` с download/upload MinIO и записью в таблицу `runs`. Паттерн с `custom_types_service.py`. |
| `backend/src/api/services/ocr_service.py` | **NEW.** `extract_ocr(object_name)` — download → `ingest_pdf(..., ocr=select_ocr())` для PDF, `ingest_image(..., ocr=select_ocr())` для картинок, вытаскивает OCR-сегменты (у которых `origin=="ocr"`) в JSON. |
| `backend/src/api/models/run.py` | **NEW.** `RunORM(id, thread_id, owner_user_id, file_name, object_name, status, created_at, finished_at, options_json, report_json, artifacts_json)`. |
| `backend/src/api/schemas/run.py` | **NEW.** Pydantic-схемы под всё выше. `HighlightOut` — заглушка (в этом плане возвращаем `[]`, реальный формат — в feat-highlight-coords-edits). |
| `backend/src/api/schemas/ocr.py` | **NEW.** `OcrExtractRequest/Response`, `OcrPageOut`, `OcrLineOut`. |
| `backend/migrations/versions/<hash>_add_runs_table.py` | **NEW.** alembic-миграция под `runs`. |
| `backend/src/api/main.py` | Подключить два новых router'а. |
| `backend/src/masker/run.py` | В `RunOptions` добавить `image_output_format` (сделает feat-image-ingest — этот план ссылается на поле). Здесь ничего не трогаем. |
| `backend/src/api/services/runs_service.py::_write_artifacts_to_minio` | После `start_run`/`resume_run` пройтись по `artifacts_of(outcome)`, залить каждый в `runs/{thread_id}/{name}` (bucket из `settings.minio_bucket`) с `content_type` по расширению. Артефакты локально живут в `Path(tempfile.mkdtemp())` — удалить в `finally`. |
| `backend/src/api/services/runs_service.py::_presigned_urls` | `minio_client.presigned_get_object(bucket, name, expires=timedelta(seconds=600))`. |
| `backend/src/api/services/runs_service.py::_persist_run` | INSERT/UPDATE в `runs`. Owner берётся из `Depends(get_current_user)`. |
| `backend/tests/api/test_runs.py` | **NEW.** Smoke: `POST /files/upload` mock-файлом → `POST /runs` (Fake-LLM, Fake-OCR) → status=done, есть presigned URL, отчёт непустой. |
| `backend/tests/api/test_runs_history.py` | **NEW.** `POST /runs` × 3 → `GET /runs` возвращает 3 записи, `GET /runs/{tid}` даёт отчёт. |
| `backend/tests/api/test_runs_waiting.py` | **NEW.** interactive-прогон уходит в `waiting`, `POST /answers` завершает. |
| `backend/tests/api/test_ocr_extract.py` | **NEW.** `POST /api/ocr/extract` на PDF со скан-страницей возвращает OCR-строки; на текстовом PDF — пустые `pages[*].lines`. |
| `backend/tests/api/conftest.py` | Уже есть? Проверить фикстуры авторизации, `MASKER_OCR=fake`, `MASKER_LLM=fake` в тестах API. |
| `backend/masker.example.yaml` | В комменте к секции `ocr` явно упомянуть, что OCR-настройки только серверные. |
| `docs/plans/feat-api-runs.md` | Этот файл. |

## Инварианты API

1. **Никакие OCR-параметры не попадают в тело запроса.** `provider`, `dpi`,
   `force_ocr` — всё через yaml/env. Иначе `thread_id_for` начнёт разваливаться
   на два thread_id для одного и того же файла с разной картинкой мира.
2. **Presigned URL — короткоживущие** (600 сек). Артефакты живут в MinIO
   постоянно, но URL не хранятся в БД.
3. **Артефакты не отдаются в теле ответа**, даже base64. Только object_name +
   presigned URL.
4. **История — SQL, а не чекпойнтер.** `SqliteSaver` не переживает падение
   процесса корректно на конкурентных прогонах; `RunORM` пишется в общий
   PostgreSQL, чекпойнтер остаётся как есть под сам граф.
5. **Owner-фильтрация.** `GET /runs` и `GET /runs/{tid}` — только под своим
   `user_id`. Админ (`Role.ADMIN`) видит всё через тот же эндпоинт (флаг в
   `get_current_user`).
6. **Идемпотентность старта.** `POST /runs` с тем же `object_name` и теми же
   опциями попадёт в тот же `thread_id` через `thread_id_for` — сервер не
   создаёт две записи в `runs` для одной идентичности; вернёт существующую
   запись со статусом. Это опирается на детерминистичный `thread_id`
   (`run.py` уже так делает).
7. **`highlights: []` — не сюрприз.** Пустой массив — валидный ответ по
   контракту; фронту разрешено полагаться на форму, не на содержимое.
   Заполнение — в плане feat-highlight-coords-edits.

## Порядок работ

### А1 — модель БД и заглушки роутов
- `RunORM` + миграция alembic;
- каркас роутов (401/422, но не 200);
- смоук `POST /runs` возвращает 501 «Not implemented», но регистрируется.

Приёмка: `alembic upgrade head` и `pytest` c 501-заглушкой.

### А2 — реальный старт прогона
- `start_masker_run`, download/upload MinIO;
- 200 для Fake-LLM/Fake-OCR;
- `POST /runs` без interactive-режима.

Приёмка: `test_runs.py::test_start_run_done`.

### А3 — interactive + answers
- `answer_masker_questions`, роут `/answers`.

Приёмка: `test_runs_waiting.py`.

### А4 — история
- `list_runs`, `get_run`, owner-фильтр.

Приёмка: `test_runs_history.py`.

### А5 — OCR-эндпоинт
- `ocr_service.extract_ocr`, роут, схема.

Приёмка: `test_ocr_extract.py` на скан-PDF из fixtures.

### А6 — интеграция с картинками (после мержа feat-image-ingest)
- `image_output_format` пробрасывается из тела запроса.
- Тест: `POST /runs` c картинкой → артефакт возвращается как `.jpg`.

Приёмка: `test_runs.py::test_start_run_image`.

## Возможные грабли

- **Async и SqliteSaver.** Чекпойнтер синхронный; всё, что зовёт `start_run`,
  крутится в `run_in_threadpool`. Не пытаться `async`-фикстуризовать `SqliteSaver`.
- **MinIO presigned URL и обратные прокси.** Presigned URL строится от
  `minio_endpoint` из settings; за nginx/traefik может понадобиться
  `external_endpoint` — фиксируем `settings.minio_public_endpoint` (fallback
  на `minio_endpoint`). Задел, но реализовать сразу.
- **`options.styles` и thread_id.** Не входит в `canonical()` — это уже
  учтено в `run.py`. Не менять.
- **Owner-фильтр в admin-виде.** Не смешивать роуты; один `/runs`, флаг
  `all=true` доступен только `Role.ADMIN`.
- **Артефакты и утечки.** MinIO-бакет должен быть **private**. `ensure_bucket`
  проверяет только existence — добавить в `main.py` проверку policy, если
  инстанс не за периметром.

## Определение готовности

1. `make gate` зелёный (pytest, mypy, ruff, метрики).
2. Все шесть шагов А1–А6 закрыты, соответствующие тесты в CI.
3. OpenAPI-схема (`/docs`) содержит `/runs`, `/runs/{tid}/answers`,
   `/runs/{tid}`, `/runs`, `/ocr/extract`.
4. Ручной smoke: `curl -H "Authorization: Bearer ..."` на все пять роутов
   — приложить в PR-описание.
5. `TASKS.md`: В1 и В8 переведены в состояние «сделано».
