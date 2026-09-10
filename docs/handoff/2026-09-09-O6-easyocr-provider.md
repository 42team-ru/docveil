# O6 — EasyOCR-провайдер (хендофф)

Дата: 2026-09-09  
Ветка: `feat/easyocr-provider`  
Последний коммит: `b70535d`

## Что сделано

Добавлен четвёртый нейронный OCR-движок — **EasyOCR** (JaidedAI, Apache-2.0).
Активируется через `MASKER_OCR=easy`.

### Новые файлы

| Файл | Описание |
|------|----------|
| `backend/src/masker/ocr/easy.py` | `EasyOCRProvider`: ленивая инициализация, BGR→RGB, парсинг `(bbox_4pt, text, conf)` → `OCRLine`. |
| `backend/tests/masker/ocr/test_easy_smoke.py` | Smoke-тест `@pytest.mark.ocr`: синтетический PNG с ИНН, проверка confidence/bbox/детерминизма. |

### Изменённые файлы

| Файл | Что добавлено |
|------|---------------|
| `backend/src/masker/ocr/select.py` | Фабрика `_make_easy()` + `"easy"` в реестр (строка 115). |
| `backend/pyproject.toml` | `easyocr>=1.7` в `[project.optional-dependencies].ocr`. |
| `backend/tests/masker/ocr/test_select.py` | `test_provider_without_extra_raises_clear_error` параметризован на `("easy", "easyocr", "easyocr>=1.7")`. |
| `backend/tests/masker/ocr/test_layer_boundary.py` | `"easyocr"` в `FORBIDDEN_MODULES`. |
| `backend/uv.lock` | Обновлён после добавления `easyocr`. |

### Попутные фиксы (pre-existing в `feat/ocr-scan-render`)

- `cli.py`: укорочен комментарий EXIT_* → 449 строк (тест требует < 450).
- `tests/masker/ingest/test_pdf_scan_router.py`: ожидаемые координаты якоря
  пересчитаны под DPI=400 (коммит `fbde4d6` поднял DPI с 300 до 400,
  тест остался со старыми числами).

## Как пользоваться

```bash
MASKER_OCR=easy make demo
# или
MASKER_OCR=easy python -m masker.cli document.pdf --out out/ --types all
```

Первый запуск скачает веса (~64 MB CRAFT-детектор + ~30 MB ru-рекогнайзер)
в `~/.EasyOCR/model/`. Повторные прогоны быстрее.

GPU включается флагом `MASKER_OCR_GPU=1`. По умолчанию CPU-режим.

## Производительность

| Режим | Время/страница A4 @400 DPI | Примечание |
|-------|---------------------------|------------|
| RapidOCR (ONNX) | ~150 мс | текущий дефолт для prod |
| EasyOCR CPU | ~600–2000 мс | зависит от плотности текста |

EasyOCR значительно медленнее. Использовать для задач, где нужна более
высокая точность (мелкие цифры, нестандартные шрифты), а скорость второстепенна.

## Весовой кэш в офлайн-среде

Если машина без интернета, предзагрузить один раз:
```bash
MASKER_OCR=easy python -c "from masker.ocr.easy import EasyOCRProvider; EasyOCRProvider()._get_reader()"
```
Или вручную поместить файлы в `~/.EasyOCR/model/`.

## Thread-safety

`EasyOCRProvider` thread-safe: `_reader` инициализируется один раз под
`threading.Lock()`, дальнейшие `recognize()` параллельны. Это симметрично
`RapidOCRProvider` и `PaddleOCRProvider`.

## Известные ограничения

- Первый `recognize()` медленный: инициализирует PyTorch + загружает модель.
- `easyocr` тянет `torch` (~800 MB). Extra `ocr` устанавливается явно;
  базовый `pip install triema-masker` не тащит.
- Детерминизм на CPU гарантирован (тест). На GPU результат может слегка
  флуктуировать из-за нестабильного порядка CUDA-операций.
