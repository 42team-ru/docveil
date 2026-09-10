# O6 — EasyOCR-провайдер (`MASKER_OCR=easy`)

## Context

Существующие OCR-провайдеры: `fake` (CI-safe), `paddle` (PaddleOCR PP-OCRv5),
`paddle_vl` (заглушка), `rapid` (RapidOCR через onnxruntime, дефолт для локальных
прогонов) и `tesseract`. Реестр — `src/masker/ocr/select.py` строки 100+.

RapidOCR быстрый и лёгкий, но иногда путает разрывы слов и мелкие цифры (типа
последних цифр ИНН на плохо отсканированной строке). EasyOCR (JaidedAI) —
альтернативный нейронный движок на PyTorch: медленнее, но на некоторых
русскоязычных сканах точнее. Задача — дать возможность переключаться между
`rapid` и `easy` через env-переменную без правки кода потребителей.

Дефолт остаётся `fake` для CI. `easy` — опциональная зависимость, не
подтягивается без extras.

## Ветка

```bash
git switch -c feat/easyocr-provider  # от feat/ocr-scan-render
```

## Изменения

| Файл | Действие |
|------|----------|
| `backend/src/masker/ocr/easy.py` | **NEW.** `EasyOCRProvider` по контракту `OCRProvider` из `provider.py`. |
| `backend/src/masker/ocr/select.py` | Добавить `"easy"` в `_REGISTRY` (строка ~100) + фабрику `_make_easy()` с ленивым импортом и ясной ошибкой при отсутствии пакета (по паттерну `_make_rapid`, строки 84–95). |
| `backend/pyproject.toml` | В `[project.optional-dependencies].ocr` добавить `easyocr>=1.7`. |
| `backend/tests/masker/ocr/test_select.py` | Параметризовать существующие тесты именем `easy`. Добавить тест «`easy` без установленного пакета → `OCRError` с install-hint». |
| `backend/tests/masker/ocr/test_easy_smoke.py` | **NEW.** Параллель к `test_paddle_smoke.py`: синтетическая PNG с русским текстом и ИНН `7707083893`, проверка полноты распознавания (confidence ≥ 0.85), геометрии bbox и детерминизма повторных вызовов. Маркер `@pytest.mark.ocr`. |
| `backend/tests/masker/ocr/test_layer_boundary.py` | Добавить `easyocr` в список запрещённых прямых импортов вне `src/masker/ocr/`. |
| `docs/handoff/2026-09-XX-O6-easyocr-provider.md` | **NEW.** Хендофф: что вошло в MVP, где кэшируются веса (`~/.EasyOCR/model/`), затраты по памяти в CPU-режиме, инвариант thread-safety, известные различия с RapidOCR. |

## Контракт `EasyOCRProvider`

- Приватная `_get_reader()` с `threading.Lock` (паттерн `rapid.py:48–53`),
  ленивый `easyocr.Reader(['ru'], gpu=<flag>)`. Флаг GPU — из env
  `MASKER_OCR_GPU=1`.
- `recognize(image, dpi)`:
  - вход — BGR uint8 `(H, W, 3)` (ingest всегда даёт BGR через PyMuPDF pixmap);
  - EasyOCR ждёт RGB — конвертация `image[..., ::-1]` (без копии), потом
    `np.ascontiguousarray`;
  - вызов `reader.readtext(rgb, detail=1, paragraph=False)` возвращает
    `list[tuple[bbox_4pt, text, conf]]`;
  - парсинг в `OCRLine` (helper `_parse_results` по паттерну `rapid.py:112–142`):
    - `polygon` — 4 угла в порядке TL → TR → BR → BL из EasyOCR (проверить и
      при необходимости привести),
    - `bbox` — axis-aligned min/max из полигона,
    - `confidence` — `float(conf)` в `[0, 1]`,
    - `order` — индекс в списке (EasyOCR уже сортирует top→bottom, left→right).
- Пустой результат — пустой tuple, не исключение.
- DPI игнорируется провайдером (масштабирование — забота `scan_ingest.py`).
- Валидация входа: `image.dtype == np.uint8`, `image.ndim == 3`, `shape[2] == 3` —
  иначе `ValueError` (см. паттерн в `fake.py`).

## Приёмка

1. `make gate` завершается кодом 0. Вывод приложить целиком.
2. `pytest -q backend/tests/masker/ocr/test_select.py` — все параметризации
   зелёные, включая новую с `easy`.
3. `pytest -q -m ocr backend/tests/masker/ocr/test_easy_smoke.py` (при
   установленном extras `ocr`) — детерминистично находит ИНН, confidence ≥ 0.85.
4. `pytest -q backend/tests/masker/ocr/test_layer_boundary.py` — не пропускает
   прямые импорты `easyocr` вне `src/masker/ocr/`.
5. Ручная проверка: `MASKER_OCR=easy make demo` на
   `backend/fixtures/non-text-pdfs/*.pdf` — прогон завершается, отчёт содержит
   осмысленные строки.

## Что НЕ входит

- Автоматический fallback между провайдерами (`rapid` → `easy` → `fake`) —
  не делаем, явный выбор по env.
- Оптимизация первой загрузки моделей — как есть, ленивая инициализация.
- Сравнительные бенчмарки precision/recall между `rapid` и `easy` — отдельная
  задача при необходимости.

## Известные ограничения (в handoff)

- Первый прогон качает веса (~64 MB для детектора + ~30 MB для распознавания
  ru) в `~/.EasyOCR/model/`. В офлайн-среде их надо предзагрузить.
- В CPU-режиме одна страница A4 при 400 DPI обрабатывается ощутимо медленнее
  RapidOCR (порядок разницы — в handoff после замера).
- `easyocr` тянет `torch` — размер образа/окружения растёт. Extras `ocr`
  устанавливается только при необходимости.
