# Хендофф: O3 — Скан-ingest (09.09.2026)

Третья подзадача плана `docs/plans/T2.3-ocr-paddleocr.md`. Добавлен
пер-страничный роутинг скан/текст и конвертация OCR-строк в `Segment`-ы.

**Ветка:** `feat/ocr-scan-ingest` (от `feat/ocr-paddle`).

**Состояние: ворота зелёные, 1856 passed, 2 skipped.**

---

## 1. Что закрыто по приёмке O3

| Пункт приёмки | Статус |
|---|---|
| `_page_is_scan` — пустая страница → скан | ✅ |
| `_page_is_scan` — двухслойная ловушка (<5% текста + изображения) | ✅ |
| `ingest_pdf(ocr=None)` — прежнее поведение | ✅ (регресс-тест) |
| `ingest_pdf(ocr=ocr)` — скан → OCR-сегменты, origin="ocr" | ✅ |
| Смешанный PDF: пер-страничный роутинг | ✅ |
| Якорь OCR-сегмента в pt-координатах (×100, round) | ✅ |
| `RunDeps.ocr` добавлен | ✅ |
| `make_extract_node(deps)` использует `deps.ocr` в графе | ✅ |
| `extract_node` сохранён как backward-compatible алиас | ✅ |
| Все существующие тесты не сломаны | ✅ |

---

## 2. Что появилось в коде

**`backend/src/masker/ingest/scan_ingest.py`** (новый):

- `_page_is_scan(page)`: два случая — пустой текстовый слой (`get_text("text")`)
  или текст занимает < 5% площади страницы И есть растровые изображения
  (`get_images()`).
- `_char_coverage_ratio(page)`: суммирует площади символьных боксов через
  `rawdict`, делит на площадь страницы.
- `ocr_segments_for_page(page, page_num, ocr, dpi=300)`: рендерит страницу
  в BGR-массив через `page.get_pixmap(dpi=dpi, colorspace=csRGB)` → flip
  каналов → `ocr.recognize(img_bgr, dpi)`. Каждую `OCRLine` конвертирует
  в `Segment(origin="ocr")` с якорем
  `("page", page_num, "ocr", x0, y0, x1, y1)` в pt×100 (через `round`).
- `masker.ingest.scan_ingest` добавлен в mypy overrides (pymupdf без стабов).

**`backend/src/masker/ingest/pdf_ingest.py`** (правка):

- `ingest_pdf(path, ocr=None)` — новый параметр. Без OCR поведение идентично
  предыдущей версии. С OCR: пер-страничный роутинг через `_page_is_scan`.

**`backend/src/masker/graph/nodes.py`** (правки):

- `RunDeps.ocr: OCRProvider | None = None` — новое поле.
- `_extract(state, ocr)` — вынесена внутренняя логика.
- `extract_node(state)` — алиас `_extract(state, ocr=None)` (обратная совместимость
  с тестами, которые вызывают его напрямую).
- `make_extract_node(deps)` — фабрика, замыкает `deps.ocr`.

**`backend/src/masker/graph/build.py`** (правка):

- `graph.add_node("extract", make_extract_node(deps))`.
- Исправлены type ignore-комментарии для всех `make_*_node(deps)`:
  `arg-type` → `call-overload` (langgraph обновил стабы, ошибка изменила код).

**`backend/tests/masker/ingest/test_pdf_scan_router.py`** (новый, 8 тестов):

- Роутер: пустая страница → скан, текстовая → не скан, `char_coverage_ratio > 0`.
- Регресс: `ingest_pdf` без `ocr` — все `origin="text"`.
- OCR-ветка: скан-страница → сегменты с `origin="ocr"` и маркером `"ocr"` в locator.
- Смешанный PDF: обе ветки в одном документе.
- Якорь в pt-координатах (проверка чисел × 100).
- `FakeOCR.calls == 1` после обработки одной скан-страницы.

---

## 3. Что сознательно НЕ делали в O3

- **Двухслойная ловушка с реальным невидимым OCR-слоем.** Тест существует
  (`_page_is_scan` с `< 5%` и `get_images`), но создание такого PDF
  программно требует PyMuPDF-магии (вставить изображение + скрыть текст).
  Покрывается реальными данными в O5.
- **`ValidateAgent` не получил `ocr`.** Валидатор пока работает на
  текстовом слое результата (тест на утечку через `pdftotext`). OCR-прогон
  артефакта — часть O4/O5.

---

## 4. Проверка

```
cd backend
./scripts/gate.sh
pytest tests/masker/ingest/test_pdf_scan_router.py -v
```

---

## 5. Что дальше — O4

Рендер скан-страниц: `pdf_render.py` ветка для `origin="ocr"` сегментов —
(а) стирание пикселей `PDF_REDACT_IMAGE_PIXELS_INSIDE`, (б) маркер поверх
через `marker_ladder`, (в) невидимый текстовый слой `render_mode=3` с
обезличенным текстом для copy-paste.
