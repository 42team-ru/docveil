# Хендофф: O2 — PaddleOCR-адаптер (09.09.2026)

Вторая подзадача плана `docs/plans/T2.3-ocr-paddleocr.md`. Создан реальный
провайдер PP-OCR поверх `paddleocr>=3.0`; gate остался зелёным без весов.

**Ветка:** `feat/ocr-paddle` (от `feat/ocr-provider-abstraction`).

**Состояние: ворота зелёные, 1848 passed, 2 skipped.**

---

## 1. Что закрыто по приёмке O2

| Пункт приёмки | Статус |
|---|---|
| `PaddleOCRProvider` в `masker.ocr.paddle` | ✅ |
| Ленивая инициализация модели | ✅ |
| Фолбэк `lang="ru"` → `"cyrillic"` | ✅ |
| `PaddleVLProvider` — скелет | ✅ (зарегистрирован как `paddle_vl`) |
| `gate.sh` исключает `@pytest.mark.ocr` | ✅ |
| Smoke-тест `@pytest.mark.ocr` на PNG «Иванов ИНН 7707083893» | ✅ |
| `make gate` = 0 без `paddleocr` в окружении | ✅ |

---

## 2. Что появилось в коде

**`backend/src/masker/ocr/paddle.py`** (новый):

- `PaddleOCRProvider` — реализует `OCRProvider` Protocol.
  - `__init__`: проверяет `import paddleocr` на этапе создания — `OCRError`
    с текстом про `triema-masker[ocr]` вместо голого `ImportError`.
  - `_get_model()`: double-checked lock, thread-safe ленивая загрузка весов.
  - `recognize(image, dpi)`: валидация формы `(H, W, 3)`, вызов
    `model.predict(image)`, парсинг через `_parse_results`.
- `_load_paddle_model()`: пробует `lang="ru"`, при Exception пробует
  `lang="cyrillic"` (второй фолбэк). Параметры зафиксированы:
  `use_doc_orientation_classify=True`, `use_textline_orientation=True`,
  `use_doc_unwarping=False`.
- `_parse_results(raw)`: из каждого результата `predict()` извлекает
  `rec_texts`, `rec_scores`, `rec_polys`; конвертирует numpy-полигон
  `(4, 2)` в typed tuple 4×(float,float); строит `OCRLine` с axis-aligned
  bbox (min/max по осям).
- `PaddleVLProvider` — класс-заглушка, `recognize()` поднимает `OCRError`.

**`backend/src/masker/ocr/select.py`** (правка):

- Добавлен `_make_paddle_vl()` и ключ `"paddle_vl"` в `_REGISTRY`.

**`backend/scripts/gate.sh`** (правка):

- pytest-фильтр изменён с `"not gliner and not e2e"` на
  `"not gliner and not e2e and not ocr"`. Тесты с `@pytest.mark.ocr`
  (нужен реальный движок + веса) из CI исключены.

**`backend/tests/masker/ocr/test_paddle_smoke.py`** (новый, `@pytest.mark.ocr`):

- `test_paddle_recognize_finds_inn` — ИНН 7707083893 найден, confidence ≥ 0.9.
- `test_paddle_recognize_returns_valid_bbox` — все `OCRLine` имеют x0<x1,
  y0<y1, polygon из 4 точек, confidence ∈ [0,1].
- `test_paddle_recognize_deterministic` — два вызова дают одинаковый текст.
- Тест пропускается (`pytest.skip`) если `paddleocr` не установлен.

---

## 3. Что сознательно НЕ делали в O2

- **Реальная реализация `PaddleVLProvider`** — SGLang 1.7B, отдельная
  итерация. Класс зарегистрирован, `recognize()` поднимает `OCRError`.
- **`tesseract`-провайдер** — `_make_tesseract()` ссылается на
  `masker.ocr.tesseract`, который ещё не создан. Аналогично O1/paddle:
  `OCRError` при отсутствии модуля.
- **Smoke-тест с реальным кириллическим PNG** — PNG генерируется
  через Pillow в памяти прямо в тесте; DejaVu не содержит кирилличних
  глифов, поэтому реальная проверка распознавания «на кириллице» требует
  запуска с весами, что и предполагает маркер `ocr`.

---

## 4. Проверка

```
cd backend
./scripts/gate.sh        # без paddleocr — ворота зелёные

# Локально с весами:
uv sync --extra ocr
pytest -m ocr -v tests/masker/ocr/test_paddle_smoke.py
```

---

## 5. Что дальше — O3

Скан-ingest: пер-страничный роутер `_page_is_scan(page)` в
`pdf_ingest.py`, вспомогательный `scan_ingest.py`, расширение `RunDeps`
полем `ocr: OCRProvider`, правки `extract_node`. Сегменты из OCR получают
`origin="ocr"` и bbox-якорь в pt-координатах страницы.
