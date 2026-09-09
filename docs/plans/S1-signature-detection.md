# S1 — Детекция и замазывание рукописных подписей (PDF, MVP)

## Context

Рукописная подпись — тоже персональные данные. Сейчас пайплайн её не видит:
детекторы `RuleDetector`/`AddressDetector`/`DateDetector`/Natasha работают
только над текстом, а подпись — графика. На выходе она остаётся живой
картинкой в PDF.

Пути появления подписи в документе:
- **скан-PDF** — подпись как часть растрового изображения страницы (OCR-путь
  из `scan_ingest.py`, страница уже растеризована);
- **текстовый PDF со встроенной картинкой подписи** — текстовый слой её не
  описывает, ingest её пропускает;
- **«двухслойный» скан** — растровая подпись + OCR-текст сверху (уже
  маршрутизируется в OCR-путь, см. `scan_ingest.py:45–77`).

MVP покрывает только PDF (текстовые и скан). DOCX/XLSX встроенные
изображения — вне scope, известное ограничение, отдельная задача:
`docx_ingest.py` сейчас читает только текст, обход `w:drawing`/`v:shapetype`
надо проектировать отдельно.

Стратегия — гибридная: классический CV работает всегда, опциональная
ML-модель (Conditional-DETR, Apache-2.0) включается через env-переменную
по аналогии с OCR-провайдерами. Красный флаг `ultralytics`/AGPL-3.0 обойдён
выбором DETR.

Маркер подписи — `[ПОДПИСЬ]` (без role-префикса и нумерации). Ролевая
привязка — будущая доработка.

## Ветка

```bash
git switch -c feat/signature-detection  # от feat/ocr-scan-render
```

## Стратегия детекции

Оба детектора работают на растровом изображении страницы (BGR ndarray)
и возвращают общий `SignatureCandidate(bbox_px, confidence, source)`.

### Слой 1 — `SignatureCVDetector` (классика, всегда включён)

Файл: `backend/src/masker/detect/signature_detector.py`.

Шаги:
1. Растеризация страницы 300 DPI — переиспользовать существующий рендер из
   `scan_ingest.py:80` (в scan-пути pixmap уже есть; в текстовом пути —
   отдельный рендер, кэшируется на прогон).
2. Маскирование текстовых регионов: bbox-ы из OCR-сегментов (для scan) или
   `page.get_text("blocks")` (для текстового PDF) — эти области выкидываются
   из кандидатов.
3. Адаптивная бинаризация (`cv2.adaptiveThreshold`) → морфология
   `MORPH_CLOSE` небольшим ядром → `cv2.connectedComponentsWithStats`.
4. Фильтр кандидатов:
   - **площадь** — 0.5–15 % площади страницы;
   - **плотность штрихов** — доля тёмных пикселей внутри bbox 5–30 %
     (текст плотнее, штампы либо плотнее, либо в виде рамки);
   - **соотношение сторон** — 0.3–5;
   - **непрямолинейность** — отношение периметра контура к периметру bbox
     ≥ 2.0 (отсекает штампы-прямоугольники, таблицы);
   - **не-текстовость** — если regionprops overlap с OCR-bbox > 30 % —
     отбрасываем.
5. `confidence` из эвристики: чем ближе к «идеальным» диапазонам, тем выше
   (0.3–0.7).

### Слой 2 — `SignatureDETRDetector` (опционально, `MASKER_SIGNATURE=detr`)

- `tech4humans/conditional-detr-50-signature-detector` через `transformers`
  (Apache-2.0). Ленивый импорт `AutoImageProcessor`, `AutoModelForObjectDetection`.
- CPU-first: `device_map=None`, `torch.set_num_threads` не трогаем.
- При `MASKER_SIGNATURE=detr` DETR **дополняет** классику: сначала DETR
  (confidence ∈ [0.5, 0.99]), потом CV на оставшихся регионах; при
  пересечении bbox → объединение (`box_a | box_b`), `confidence` — max.
- Без `transformers` в окружении — ясная ошибка install-hint (паттерн
  `select.py:52–63`).

### Реестр детекторов

`backend/src/masker/detect/signature_select.py` — паттерн `ocr/select.py`.
Значения: `cv` (дефолт), `detr`, `fake` (для тестов). Env — `MASKER_SIGNATURE`.

## Интеграция в граф

- **Тип сущности**: `EntityType.SIGNATURE` в `backend/src/masker/model.py`.
  **НЕ** включать в `CRITICAL_TYPES` — при низкой уверенности идём в
  `ask_human`, а не в silent-mask.
- **Реестр**: в `backend/src/masker/entity_types.py::builtin_specs()`
  (строки 27–62) — новый built-in spec `id="signature"`, `title="Подпись"`,
  `marker_label="ПОДПИСЬ"`.
- **Локатор**: 7-tuple `("page", page_num, "signature", x0, y0, x1, y1)` в
  сотых pt. Конверсия pixel→pt по DPI — по паттерну `scan_ingest.py:104–114`.
  Отдельный тег `signature` в третьей позиции локатора, чтобы отличать от
  OCR-текста в рендере.
- **Маркер**: `mask/labels.py::compose_marker` — частный случай для
  `SIGNATURE`: возвращает `[ПОДПИСЬ]` без role/номера, независимо от
  профиля и роли.
- **RunDeps**: `backend/src/masker/graph/state.py` — новое поле
  `signature: SignatureDetector | None`.
- **CLI**: `backend/src/masker/cli.py:254` — рядом с `select_ocr()` вызов
  `select_signature()`, передача в `RunDeps.signature`.
- **Detect-нода**: `backend/src/masker/graph/nodes.py::make_detect_node`
  (строки 180–233) — после трёх слоёв текстовой детекции добавить прогон
  `signature_detector` на всех страницах документа; результаты
  преобразовать в `Entity(type=SIGNATURE, source=Source.CV|Source.ML,
  confidence=...)`.
- **Разбиение по уверенности** — новый helper `resolve_signature_candidates`:
  - `confidence ≥ 0.8` → CONFIRMED, маскируется молча;
  - `0.5 ≤ confidence < 0.8` → в `state["questions"]` (одной пачкой, см.
    `build_ask_payload` в `graph/nodes.py:320`), обрабатывается `ask_human`;
  - `< 0.5` → отбрасывается.

## Ingest-путь

- **Scan PDF** — уже растеризует страницу. Прокинуть pixmap до
  detect-ноды через `state["meta"]["page_rasters"]` (in-memory кэш, не
  сериализуется в checkpoint).
- **Text PDF** — в `backend/src/masker/ingest/pdf_ingest.py` для каждой
  страницы дополнительно рендерить pixmap 300 DPI и класть в тот же кэш.
  Одна страница = один rasterize, не повторять.

## Замазывание

**Ничего нового в рендере писать не надо**: `apply_redactions(images=
PDF_REDACT_IMAGE_PIXELS)` в `render/pdf_render.py:1053` уже стирает
пиксели в bbox, включая embedded images, и обеспечивает контракт
«текст под чёрным прямоугольником недопустим».

Дополнения в `render/pdf_render.py`:
- для entities `type=SIGNATURE` — не пытаться делать 12pt-квантование
  (bbox визуальный, не текстовый); оставить bbox как есть;
- маркер `[ПОДПИСЬ]` вписывается через существующий `label_region`
  (marker ladder с fallback до 8pt);
- в `plan_agent` для SIGNATURE не искать «оригинальный текст» —
  `original_text=""`.

## Изменения

| Файл | Действие |
|------|----------|
| `backend/src/masker/detect/signature_detector.py` | **NEW.** `SignatureCVDetector`, `SignatureDETRDetector`, `FakeSignatureDetector`, общий контракт-протокол. |
| `backend/src/masker/detect/signature_select.py` | **NEW.** Реестр `cv|detr|fake`, дефолт `cv`, env `MASKER_SIGNATURE`. |
| `backend/src/masker/model.py` | Добавить `EntityType.SIGNATURE`. **НЕ** в `CRITICAL_TYPES`. Добавить `Source.CV`, `Source.ML` при отсутствии. |
| `backend/src/masker/entity_types.py` | Built-in spec в `builtin_specs()` (строки 27–62). |
| `backend/src/masker/mask/labels.py` | Частный случай `compose_marker` для `SIGNATURE` — `[ПОДПИСЬ]` без role/номера. |
| `backend/src/masker/graph/state.py` | `RunDeps.signature: SignatureDetector \| None`; `State["meta"]["page_rasters"]` — типизированный in-memory кэш. |
| `backend/src/masker/graph/nodes.py` | В `make_detect_node` (180–233) прогон детектора подписей + helper `resolve_signature_candidates` для разбиения по уверенности. |
| `backend/src/masker/ingest/pdf_ingest.py` | Для текстовых PDF рендер каждой страницы в pixmap 300 DPI, кэш в `state["meta"]["page_rasters"]`. |
| `backend/src/masker/ingest/scan_ingest.py` | Отдать существующий pixmap в `page_rasters` (без повторного рендера). |
| `backend/src/masker/render/pdf_render.py` | Для `type=SIGNATURE` — обход 12pt-квантования, `original_text=""`. |
| `backend/src/masker/cli.py` | `select_signature()` рядом с `select_ocr()` (строка 254), проброс в `RunDeps.signature`. |
| `backend/pyproject.toml` | Новый extras-group `signature = ["transformers>=4.40", "torch>=2.0"]`; `opencv-python` — в основные deps, если ещё не там. |
| `backend/tests/masker/detect/test_signature_cv.py` | **NEW.** Синтетический скан с нарисованной подписью (кривая линия через PIL/cv2) → детектор находит bbox, confidence > 0.5. Документ без подписи → 0 кандидатов ≥ 0.5. |
| `backend/tests/masker/detect/test_signature_pipeline.py` | **NEW.** E2E-мини: PDF с embedded-image подписью → в отчёте `[ПОДПИСЬ]`, побайтовая проверка, что исходной картинки в выходе нет (`page.get_images()` пуст либо изменён). |
| `backend/tests/masker/detect/test_signature_confirm.py` | **NEW.** Кандидат с confidence 0.6 → попадает в `state["questions"]`; ответ «да» → маскируется; «нет» → выкидывается. |
| `backend/tests/masker/detect/test_signature_select.py` | **NEW.** Реестр `cv|detr|fake`, env-переменная, ошибка при отсутствии `transformers` для `detr`. |
| `backend/fixtures/labeled/signature_synth_01.pdf` | **NEW.** Синтетический PDF: текст + один embedded-image с «подписью» (сгенерирована в скрипте `scripts/gen_signature_fixture.py`). `.labels.json` с ожидаемым `[ПОДПИСЬ]` и bbox. |
| `backend/fixtures/non-text-pdfs/scan_with_signature_01.pdf` | **NEW.** Скан-фикстура с рукописной подписью (синтетическая). `.labels.json`. |
| `backend/scripts/gen_signature_fixture.py` | **NEW.** Скрипт генерации синтетических подписей (детерминированные штрихи через `cv2.polylines` с сидом). Запускается разово, чтобы фикстуры были воспроизводимы. |
| `docs/handoff/2026-09-XX-S1-signature-detection.md` | **NEW.** Что реализовано, какая точность на фикстурах, что осталось за scope (DOCX/XLSX, ролевая привязка). |

## Приёмка

1. `make gate` завершается кодом 0. Вывод приложить целиком.
2. Recall по SIGNATURE на новых фикстурах — > 0.85 (не критический тип,
   1.0 не требуется). Precision — > 0.7 (лишняя маска — косметика).
3. `make demo` на `signature_synth_01.pdf` и `scan_with_signature_01.pdf`:
   - в отчёте есть `[ПОДПИСЬ]`;
   - в выходном PDF `page.get_images()` не возвращает исходной картинки
     подписи (либо возвращает пустой pixmap);
   - проверка утечки: побайтовый поиск SHA-256 исходного pixmap подписи в
     выходном файле — не найдено.
4. **Идемпотентность**: второй прогон на уже обезличенном файле не
   добавляет новых `SIGNATURE` в отчёт.
5. `MASKER_SIGNATURE=detr` без установленного `transformers` — понятная
   ошибка с install-hint, не `ModuleNotFoundError`.
6. `pytest -q -m e2e backend/tests/masker/detect/` — E2E-мини зелёный.

## Что НЕ входит

- Подписи внутри DOCX/XLSX (обход `w:drawing`/`v:shapetype`) — отдельная
  задача. В handoff — известное ограничение.
- Ролевая привязка подписи к субъекту («здесь подпись директора
  поставщика») — будущая доработка.
- Детекция печатей/штампов как отдельного класса — вне scope; классика
  их частично отбраковывает.
- Тонкая настройка порогов уверенности под конкретного заказчика — оставить
  дефолт, вынести в options позже.

## Известные ограничения (в handoff)

- **DOCX/XLSX подписи не обрабатываются** — расширение `docx_ingest`
  требует отдельной задачи.
- Классика теряет подписи, наложенные на подчёркивание или в границах
  таблицы — на такие случаи полагается ML-опция или человек.
- Веса DETR (~166 MB) не пушим в репозиторий; тянутся с HuggingFace при
  первом запуске. В офлайн-среде — предзагрузить.
- Первый прогон детектора медленный (загрузка модели). Дальнейшие вызовы
  переиспользуют экземпляр в рамках процесса.
