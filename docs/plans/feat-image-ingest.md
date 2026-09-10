# План: ввод-вывод картинок через OCR-пайплайн

## Контекст

Сегодня `graph/nodes.py::_extract` знает три расширения (`.docx`/`.pdf`/`.xlsx`)
и падает с `ValueError` на всём остальном. Скан-PDF уже проходит через
пер-страничный роутер (`ingest/scan_ingest.py::_page_is_scan` +
`ocr_segments_for_page`, `Segment.origin="ocr"`), рендер скан-страницы
двухслойный (эрейз + маркер + скрытый обезличенный текст). OCR-провайдеры
собраны за `OCRProvider` (`select_ocr` через env/yaml, дефолт `tesseract`).
Задача — сделать так, чтобы одиночная картинка проходила ровно тот же граф.

**Решение в одном абзаце.** Ввести четвёртый парсер `ingest_image` (в
`src/masker/ingest/image_ingest.py`), который принимает JPEG/PNG/TIFF,
снимает и запоминает метаданные (имя, WxH, формат, каналы/bit-depth),
конвертирует одну страницу в PDF через PyMuPDF (dpi берётся из EXIF, дефолт
300), сохраняет исходное расширение и путь к бинарнику картинки в
`Document.meta`, и дальше отдаёт управление существующему `ingest_pdf` c
OCR-провайдером. После графа `render_node` строит артефакты как для
одностраничного PDF; **финальный шаг** — новый `masker.render.image_export`
конвертирует получившийся PDF-артефакт обратно в исходный формат картинки
через PyMuPDF pixmap (с восстановлением DPI и ориентации из сохранённых
метаданных). Формат вывода — по умолчанию исходный; параметр CLI/RunOptions
`--output-format=original|pdf` позволяет заказать PDF.

**Гейт документа** (картинка ли — документ?) — единственная новая логика
детекции. OCR обязателен: если распознанных строк со значащим текстом
меньше `_MIN_MEANINGFUL_LINES = 3` или суммарная длина `< 20` символов —
парсер поднимает `NotADocumentError`, узел `extract` превращает её в
`ValueError` (LangGraph заворачивает в `RunFailedError`), API отвечает
`422` с `reason="not_a_document"` и **файл в MinIO не сохраняется**
(удаляется после отказа). Порог калибруется по синтетике из fixtures.

Только одностраничный вход в MVP. Многостраничный TIFF, серии, HEIC, WebP,
BMP — не в этот план.

## Ветка

```
git switch -c feat/image-ingest  # от feat/ocr-scan-render
```

## Раскладка изменений

| Файл | Действие |
|---|---|
| `backend/src/masker/ingest/image_ingest.py` | **NEW.** `ingest_image(path, ocr)`: метаданные → одностраничный PDF в tempfile → `ingest_pdf(tmp, ocr=ocr)`; переклеивает `Document.meta` (см. ниже), закрывает PDF, удаляет tempfile через `try/finally`. Поднимает `NotADocumentError` при провале гейта. |
| `backend/src/masker/ingest/image_meta.py` | **NEW.** `ImageMetadata` (name/width/height/format/channels/bit_depth/dpi_x/dpi_y/orientation), функция `probe(path)` через Pillow (уже в зависимостях PaddleOCR/EasyOCR — проверить). Никаких зависимостей от pymupdf, чтобы можно было юнит-тестить без графа. |
| `backend/src/masker/render/image_export.py` | **NEW.** `pdf_to_image(pdf_path, meta, dst_path, target_format)`: PyMuPDF `page.get_pixmap(dpi=meta.dpi_x)` → `Pillow.Image.frombytes(...)` → сохранение в исходный формат с EXIF-стриппингом (см. инвариант ниже). |
| `backend/src/masker/model.py` | **RECOMMEND без правок.** Метаданные картинки живут в `Document.meta` строковым словарём. Если возникнет соблазн добавить `Document.image_meta` — не добавлять, иначе трогаем контракт (`AGENTS.md`, «Не менять сигнатуры в `model.py` без правки всех потребителей»). |
| `backend/src/masker/graph/nodes.py` | В `_extract` (строки 128–166) добавить ветку `.jpg/.jpeg/.png/.tif/.tiff` → `ingest_image(path, ocr=ocr)`. `coverage` — новый `image_coverage(path, document)` в `report/coverage.py` (обёртка над `pdf_coverage`, потому что после конвертации это одностраничный PDF; заголовок в отчёте берётся из `meta["image_source"]`). |
| `backend/src/masker/report/coverage.py` | Добавить `image_coverage`. |
| `backend/src/masker/cli.py` | `_SUPPORTED_SUFFIXES` (строка 53) расширить набором картинок. Новый флаг `--output-format=original|pdf` (дефолт `original`). Передать в `RunOptions`. |
| `backend/src/masker/run.py` | В `RunOptions` — `image_output_format: Literal["original", "pdf"] = "original"`. **Входит в `canonical()`** — разные форматы вывода = разные прогоны. |
| `backend/src/masker/graph/state.py` | В `options` разрешить ключ `image_output_format`; сериализовать/десериализовать. |
| `backend/src/masker/graph/nodes.py` (render) | После штатной сборки PDF-артефактов, если исходный `Document.fmt == "pdf"` **и** в `meta` есть маркер `image_source=<path.suffix>` **и** `options.image_output_format == "original"` — конвертнуть PDF-артефакты обратно в картинку через `image_export.pdf_to_image` и подменить пути в `artifacts`. |
| `backend/src/masker/validate/agent.py` | Проверка «нет исходной строки в тексте» для PDF-артефакта уже покрывает и картинку (мы валидируем **PDF до конвертации**, тк побайтовая проверка на JPEG после JPEG-сжатия бессмысленна). В отчёт добавить строку «валидация выполнена на промежуточном PDF». Проверка EXIF (не должно быть ничего кроме DPI/ориентации) — отдельным пунктом `image_metadata_stripped` в `Certificate` (`validate/certificate.py`). |
| `backend/src/masker/validate/certificate.py` | Новый `CertificateCheck(name="image_metadata_stripped")` — только для прогонов, где `meta["image_source"]` есть. Читает EXIF выходной картинки через Pillow, ok=True если остались только `DPI`, `Orientation` и ничего больше. |
| `backend/pyproject.toml` | В `[project.dependencies]` добавить `pillow>=10` (уже подтягивается easyocr/paddleocr, но у нас без extras для CI-варианта fake — Pillow должен быть в базовых, иначе `image_ingest` ломает импорт). |
| `backend/fixtures/labeled/image_01.jpg` + `.labels.json` | **NEW.** Одна PNG/JPG с ИНН, ФИО, ОГРН — сгенерирована из существующего `contract_pdf_01.docx` через `render_page_to_image`. Разметка переносится координатно. |
| `backend/fixtures/holdout/images/` | **NEW.** Каталог под 2-3 реальных фото документов, помечен `@pytest.mark.holdout_real`. В CI не гоняем. |
| `backend/scripts/make_fixtures.py` | Расширить синтезом `image_*.png` из `contract_*.docx`. |
| `backend/tests/masker/ingest/test_image_ingest.py` | **NEW.** Юниты: метаданные считаны, DPI взят из EXIF, гейт «пустая картинка → `NotADocumentError`», однопиксельный PNG отбит гейтом, обычный отсканированный документ проходит. Fake-OCR используем через `MASKER_OCR=fake`. |
| `backend/tests/masker/render/test_image_export.py` | **NEW.** Round-trip: `png → pdf → png` даёт картинку тех же размеров и того же формата; EXIF содержит только DPI и Orientation. |
| `backend/tests/masker/graph/test_extract_image.py` | **NEW.** Прогон `_extract` на картинке → в state `fmt="pdf"` (после конвертации) и `meta["image_source"]` заполнен. |
| `backend/tests/masker/test_cli.py` | Кейс: `python -m masker file.jpg` → артефакт `masked_highlight.jpg` (не `.pdf`). Кейс с `--output-format=pdf` → `.pdf`. |
| `backend/eval.py` | Скан-корпус: добавить блок `IMAGE-КОРПУС` (по аналогии с `scan_synth_*`) — метрики по картинкам, чтобы регресс не проскочил. |
| `docs/plans/feat-image-ingest.md` | Этот файл. |

## Инварианты — что нельзя нарушать

1. **EXIF-стриппинг.** На выходе только `DPI` и `Orientation`. Всё остальное
   (`Camera`, `Software`, GPS, XMP, IPTC, ICC-профиль исходной сцены, thumbnail)
   — удалить. Проверяется `image_metadata_stripped` в сертификате.
2. **Валидация на PDF, не на JPEG.** Побайтовая проверка «нет исходной строки»
   выполняется на промежуточном PDF до конвертации в картинку. JPEG после
   пересжатия побайтово уже другой файл, «поиск исходной строки в JPEG» —
   бессмысленная проверка.
3. **Гейт документа отказывает ЯВНО.** `NotADocumentError` не превращается в
   пустой результат: API возвращает 422, файл из MinIO удаляется.
4. **Метаданные документа не текут в отчёт.** `Document.meta["author"]` и
   прочие — как и раньше, чистятся `ValidateAgent`. Картиночные метаданные
   (`image_source`, `image_width`, ...) уходят в отчёт под своим ключом.
5. **Идемпотентность.** Повторный прогон на одном файле должен дать
   побайтово тот же PDF (для `output_format=pdf`) и «похожую» картинку (для
   `original`: pymupdf pixmap детерминирован, JPEG re-encode — тоже, если
   quality фиксирован; берём `quality=95`, фиксированный `optimize=False`).

## Порядок работ

Пять инкрементов, каждый — самостоятельно проходит `make gate`.

### И1 — метаданные + гейт (без графа)
- `image_meta.py` + `probe()`;
- `image_ingest.py` с гейтом, но без конвертации в PDF (`ingest_image`
  поднимает `NotImplementedError` после проверки);
- тесты на метаданные и гейт;
- Pillow в `pyproject.toml`.

Приёмка: `pytest backend/tests/masker/ingest/test_image_ingest.py`.

### И2 — конвертация в PDF и разбор
- В `image_ingest.py` конвертация через PyMuPDF (`fitz.open()` с картинкой),
  вызов `ingest_pdf(tmp, ocr=ocr)`, склейка meta;
- ветка в `_extract`, `image_coverage`;
- тест `test_extract_image.py`.

Приёмка: полный `_extract` работает на `image_01.jpg` из fixtures.

### И3 — экспорт PDF → картинка + CLI
- `image_export.py`, флаг `--output-format`, поле в `RunOptions`;
- патч `render_node` (конвертация в конце);
- тесты round-trip + CLI.

Приёмка: `python -m masker fixtures/labeled/image_01.jpg` даёт
`out/inspect/masked_highlight.jpg` без ИНН в тексте PDF-исходника рендера.

### И4 — сертификат и валидация
- `image_metadata_stripped` в `Certificate`;
- запись валидации на промежуточном PDF в отчёт.

Приёмка: `Certificate.checks` содержит новый пункт, EXIF-тест зелёный.

### И5 — корпус и метрики
- Синтетика в `make_fixtures.py`;
- блок `IMAGE-КОРПУС` в `eval.py`;
- holdout-каталог (без файлов — только README и marker).

Приёмка: `make gate` печатает секцию «IMAGE-КОРПУС» c 100% recall на
критичных типах.

## Возможные грабли

- **Pillow тянет свой libc для JPEG.** На CI в Docker должен быть
  `libjpeg-turbo`/`libpng`/`libtiff`. Уже стоят через easyocr, но проверить
  голый `python:3.14-slim` в `backend/Dockerfile`.
- **PyMuPDF из картинки строит страницу в pt = pixels * 72 / dpi.** Если
  EXIF врёт DPI, страница станет гигантской. Кэп: `max(min_dpi=72,
  min(exif_dpi, 600))`.
- **`page.get_pixmap` с `alpha=False` на PNG с прозрачностью** склеивает
  прозрачные пиксели в чёрные. Флажить: RGBA → RGB через `Image.alpha_composite`
  на белый фон перед конвертацией в PDF.
- **Ориентация из EXIF (`Orientation=6/8`)** — Pillow сама не поворачивает,
  надо через `ImageOps.exif_transpose` до конвертации в PDF, а на выходе
  проставить `Orientation=1` (нормальная), иначе двойное вращение.
- **TIFF-multipage случайно** — контролируем `img.n_frames`; > 1 → отказ с
  ясным `MultiPageNotSupported` в MVP.

## Определение готовности

1. `make gate` печатает `IMAGE-КОРПУС` и `ВОРОТА ПРОЙДЕНЫ`.
2. Все инварианты выше подтверждены тестом.
3. В fixtures/labeled/ есть `image_01.*`, в `eval.py` — секция метрик.
4. `python -m masker fixtures/labeled/image_01.jpg` работает; результат
   открывается в системном viewer как картинка того же формата.
5. Прогон на «карточке кота» (holdout) → 422 с `not_a_document`.
