# План: OCR-эндпоинт и картинки в API (delta поверх feat/union)

## Контекст

Асинхронный API прогонов уже реализован в feat/union (смержен в
`feat/ocr-scan-render` коммитом 0c8c7a3): `/api/runs` (POST 202 →
BackgroundTasks + polling), список/фильтр, статусы `queued/running/
awaiting_answers/awaiting_review/done/failed/leaked`, скачивание артефактов,
двухфазный человек-в-петле (`ask_human` + `ask_review`), таблица `runs`,
миграция `0003_create_runs.py`, тесты. Значит **все базовые роуты создавать
не нужно** — они есть.

Что осталось из старого плана (после ревизии на актуальную базу):

- Голый OCR-эндпоинт `POST /api/ocr/extract` — распознать документ, вернуть
  строки с bbox, без маскировки. В feat/union такого нет.
- Поддержка картинок в `RunCreateRequest`: пробросить `image_output_format`
  из тела запроса в `RunOptions`.
- Пробросить в `RunResponse.document.format` реальный формат вывода (если
  прогон был на картинке — `.jpg`, а не `.pdf`), чтобы фронт правильно
  скачивал.

**Не входит в этот план** (сделано в feat/union): создание/список/статусы
прогонов, ответы, review, MinIO-загрузка, история, чекпойнтер, схемы
report/run/ask/review.

**Не входит в этот план** (в feat-highlight-coords-edits): bbox-координаты
сущностей в отчёте, bbox-based `manual` правки.

**Зависит от:** feat-image-ingest (поле `image_output_format` в `RunOptions`,
`ingest_image` в `_extract`). Реализовывать после мержа image-ingest в
`feat/ocr-scan-render`.

## Ветка

```
git switch -c feat/api-ocr-and-images  # от feat/ocr-scan-render (после мержа image-ingest)
```

## Роуты

### `POST /api/ocr/extract`

Тело:
```json
{ "object_name": "uuid/scan.pdf" }
```

Ответ:
```json
{
  "provider": "tesseract",
  "pages": [
    {
      "page": 0,
      "width_pt": 595.0,
      "height_pt": 842.0,
      "dpi": 400,
      "lines": [
        {
          "text": "ИНН 7707083893",
          "bbox": [72.0, 100.0, 220.0, 118.0],
          "polygon": [[72,100],[220,100],[220,118],[72,118]],
          "confidence": 0.98,
          "order": 0
        }
      ]
    }
  ]
}
```

Поведение:
- PDF: пер-страничный роутинг (как `ingest_pdf`), OCR **только** на
  скан-страницах; для текстовых страниц `lines: []`.
- DOCX/XLSX: `422` — «формат не поддерживает OCR» (в них нет визуального
  слоя).
- Картинка: конвертируется через `ingest_image` (feat-image-ingest) в
  одностраничный PDF, дальше как PDF.
- Не сохраняет ничего в БД. Файл не удаляется из MinIO — это
  responsibility клиента.
- Провайдер OCR берётся серверным: `select_ocr()` из yaml/env, не из
  тела запроса.

Ошибки:
- `404` — object_name не найден в MinIO.
- `422` — неподдерживаемый формат.
- `500` — OCR-провайдер уронил `OCRError`.

### Расширение `POST /api/runs`

В существующую `RunCreateRequest` добавить одно поле:

```python
image_output_format: Literal["original", "pdf"] = "original"
```

- `original` — если исходник картинка, артефакт вернётся в том же формате.
- `pdf` — всегда PDF (полезно для унифицированного просмотра фронтом).
- Для не-картиночных прогонов игнорируется.

Поле **не** входит в идентичность прогона по `thread_id` (это косметика
вывода), реализуется как ветка внутри `render_node` (уже описано в
feat-image-ingest). API просто прокидывает значение в `RunOptions`.

## Раскладка изменений

| Файл | Действие |
|---|---|
| `backend/src/api/routers/ocr.py` | **NEW.** Один POST `/extract` под префиксом `/api/ocr`. Паттерн — как `custom_types.py`. |
| `backend/src/api/services/ocr_service.py` | **NEW.** `extract_ocr(session, user, object_name) -> OcrExtractResponse`. Download в tempfile → `ingest_pdf(..., ocr=select_ocr())` или `ingest_image(...)` → сбор `Segment` с `origin="ocr"` в JSON. Провайдер — `select_ocr()`, но имя вернуть в ответ через `provider` (для дебага). |
| `backend/src/api/schemas/ocr.py` | **NEW.** `OcrExtractRequest`, `OcrExtractResponse`, `OcrPageOut`, `OcrLineOut`. |
| `backend/src/api/schemas/run.py::RunCreateRequest` | Добавить поле `image_output_format: Literal["original", "pdf"] = "original"`. Пробросить в `RunOptions` в сервисе. |
| `backend/src/api/services/run_service.py::_to_run_options` (или где именно оно строится) | Проброс `image_output_format`. |
| `backend/src/api/main.py` | Подключить `ocr.router` в `api_router`. |
| `backend/tests/api/test_ocr_extract.py` | **NEW.** Кейсы: (1) PDF с одной скан-страницей → строки есть; (2) обычный текстовый PDF → `lines: []` для всех страниц; (3) DOCX → 422; (4) PNG-картинка → одна страница со строками (после мержа image-ingest); (5) неизвестный object_name → 404. Fake-OCR через `MASKER_OCR=fake`. |
| `backend/tests/api/test_runs.py` | Добавить кейс: `POST /runs` с картинкой и `image_output_format=original` → артефакт в `.jpg`. Второй кейс с `image_output_format=pdf` → `.pdf`. |
| `docs/plans/feat-api-runs.md` | Этот файл. |

## Инварианты API

1. **OCR-настройки только серверные.** `provider`, `dpi`, `force_ocr` — в
   yaml/env. `POST /ocr/extract` не принимает эти параметры в теле.
2. **`image_output_format` — косметика.** Не входит в `RunOptions.canonical()`
   (проверить, что feat-image-ingest сделал именно так; если он положил его
   в canonical() — переносим сюда).
3. **`/ocr/extract` не создаёт `RunORM`.** Просто извлечение, не прогон.
4. **Провайдер OCR в ответе — для дебага.** Не для программной логики фронта.
5. **Owner-фильтр.** `/ocr/extract` требует `Depends(get_current_user)` как
   и все остальные защищённые роуты.

## Порядок работ

Три инкремента, каждый — самостоятельно проходит `make gate`.

### А1 — OCR-эндпоинт на PDF
- Роут + сервис + схемы + тест.
- Не трогает картинки, только PDF (одна страница-скан достаточно).

Приёмка: `pytest backend/tests/api/test_ocr_extract.py`.

### А2 — Расширение RunCreateRequest под картинки
- Добавить поле в схему, проброс в `RunOptions`.
- Тест `POST /runs` на картинке (после мержа feat-image-ingest).

Приёмка: `test_runs.py::test_run_image_original_format`,
`test_runs.py::test_run_image_pdf_format`.

### А3 — Поддержка картинок в /ocr/extract
- Ветка в `ocr_service.extract_ocr` для расширений `.jpg/.png/.tif`.
- Тест на картинке.

Приёмка: `test_ocr_extract.py::test_extract_from_image`.

## Возможные грабли

- **DOCX/XLSX в `/ocr/extract`.** Соблазн — прогнать `ingest_docx`/
  `ingest_xlsx` и вернуть текст без bbox. Не делать: контракт `/ocr/extract`
  говорит про OCR со bbox, а не про парсинг текста. 422 — единственно
  правильный ответ.
- **Пустой список страниц.** Если PDF без страниц (битый) — `pages: []`
  валидный ответ, не 500. Ошибки открытия PyMuPDF — 422 с текстом.
- **Синхронно vs асинхронно.** `/ocr/extract` синхронный через
  `run_in_threadpool` — OCR быстрый (тесеракт на страницу < 3с), фронту
  paging не нужен.
- **Порядок работ.** А2 и А3 требуют мержа feat/image-ingest — не
  начинать до этого. А1 самостоятелен.

## Определение готовности

1. `make gate` зелёный.
2. Три инкремента закрыты, тесты в CI.
3. OpenAPI (`/docs`) содержит `POST /api/ocr/extract` и в
   `RunCreateRequest` виден `image_output_format`.
4. Ручной smoke на скан-PDF и на PNG.
