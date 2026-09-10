# План: координаты подсветки на фронт и правки от пользователя

## Контекст

Фронтендер рендерит PDF-артефакт (`masked_highlight.pdf`) в канвасе и хочет
поверх него подсвечивать задетекченные сущности, чтобы пользователь мог
править решения (снять маску, добавить пропущенное, поменять тип). Данные
для подсветки нужны **после** прогона, и должны координироваться с уже
готовым `masked_highlight.pdf` — то есть в координатной системе финального
рендера, а не исходного файла.

Сегодня у нас уже есть всё нужное:

- `MaskPlan.replacements: tuple[Replacement, ...]` с `paint_regions:
  tuple[PdfRegion, ...]` (`model.py:344`) — pt-координаты на странице PDF.
- `Segment.origin="ocr"` + `Segment.anchor.locator=("page", n, "ocr", x0, y0, x1, y1)`
  (`ingest/scan_ingest.py`) — pt-координаты OCR-сегментов уже нормированы
  через `pt = px * 72/dpi * 100`, целочисленно.
- `Segment.anchor.locator=("page", n, char_start, char_end)` для текстовых
  PDF — pt-геометрию читаем из `page_chars()` в `pdf_ingest.py`.
- Для docx/xlsx координат PDF-типа нет — оба формата **всегда**
  рендерятся в PDF-preview (`render/docx_preview.py`), и подсветку рисуем
  на нём.

**Решение в одном абзаце.** После завершения графа новый компонент
`highlights.build(...)` собирает список сущностей (одна сущность = один bbox
на всё вхождение) в **нормализованных 0..1 координатах по каждой странице
рендера**. Список кладётся в `report_node` под ключом `highlights` и вокруг
него в API появляется отдельный роут `PATCH /api/runs/{tid}/edits`, куда
фронт присылает набор правок (`unmask_ref`, `unmask_profile`, `unmask_type`,
`add_mask`, `change_type`). Правки не мутируют старый прогон: сервис берёт
их в `RunOptions.user_edits`, поднимает **новый** `thread_id` через
`start_run(..., fresh=False)` и запускает второй прогон, где новый узел
`apply_edits_node` (между `plan` и `render`) переупорядочивает и
дополняет `MaskPlan.replacements` до применения. Идентичность правок
кодируется как часть `canonical()`, поэтому повторные правки не создают
дубль работы.

## Ветка

```
git switch -c feat/highlight-coords-edits  # от feat/ocr-scan-render
```

## Формат `highlights` в отчёте

```json
{
  "highlights": {
    "coordinate_system": "normalized_pdf_pixels",
    "pdf_object_name": "runs/abcd/masked_highlight.pdf",
    "pages": [
      {
        "page": 0,
        "width": 1.0,   // нормализовано, всегда 1.0; фронт умножает на реальный ширину рендера
        "height": 1.0,
        "entities": [
          {
            "ref": "E17",
            "group_id": "G3",
            "profile_id": "P1",
            "type": "inn",
            "marker": "[ПОСТАВЩИК-ИНН]",
            "text": "7707083893",
            "action": "mask",           // mask | keep
            "decided_by": "critical_guard",
            "bbox": [0.1234, 0.4567, 0.2345, 0.4789],   // x0 y0 x1 y1 в долях страницы
            "origin": "text"             // text | ocr
          }
        ]
      }
    ]
  }
}
```

Инварианты формата:

- `bbox` — **union** всех `paint_regions` сущности на данной странице; если
  сущность распадается на две страницы (переносится) — две записи с одним
  и тем же `ref`, на разных страницах.
- Координаты нормализуются как `x/page.width_pt` и `y/page.height_pt` от
  `paint_region.page` (для `Replacement`) или от `page.rect` в pt (для
  необоснованных regions). Одна норма — легко перепрокрутить при zoom.
- Только сущности с `action == "mask"` в первом варианте плана — «то, что
  реально видно на подсветке». Отдельным флагом API `include_kept=true`
  можно попросить и снятые. По умолчанию — только маска.

## Раскладка изменений

| Файл | Действие |
|---|---|
| `backend/src/masker/highlights/__init__.py` | **NEW.** Публичный API: `build_highlights(document, plan, artifacts) -> dict`. |
| `backend/src/masker/highlights/coords.py` | **NEW.** Собирает pt-bbox по каждому `Replacement` (union `paint_regions`), нормализует по размеру страницы PDF-артефакта (**артефакта**, не source-PDF — размеры могут отличаться после квантизации ширины). |
| `backend/src/masker/highlights/page_dims.py` | **NEW.** Читает размеры страниц из готового `masked_highlight.pdf` через PyMuPDF. |
| `backend/src/masker/graph/nodes.py::report_node` | В сборку отчёта добавить `report["highlights"] = build_highlights(...)`. |
| `backend/src/masker/report/payload.py::build_report_payload` | Пропускать поле `highlights` наружу. |
| `backend/src/api/schemas/run.py::HighlightsOut` | Реализовать (в feat-api-runs осталось заглушкой). |
| `backend/tests/masker/highlights/test_build.py` | **NEW.** На синтетическом плане проверить: одна сущность = один bbox, многострочная = union, координаты в 0..1, `origin=ocr` пробрасывается. |
| **Правки** | |
| `backend/src/masker/graph/state.py` | В `options` — `user_edits: list[dict]` (сериализуемый). |
| `backend/src/masker/run.py::RunOptions` | Поле `user_edits: tuple[dict[str, Any], ...] = ()`. **Входит в `canonical()`** (иначе разные правки не разошлись бы по thread_id). |
| `backend/src/masker/graph/edits.py` | **NEW.** Модель правок (dataclass'ы `UnmaskRef`, `UnmaskProfile`, `UnmaskType`, `AddMask`, `ChangeType`) + `apply(plan, edits) -> plan'`. Чистая функция, тесты отдельно. |
| `backend/src/masker/graph/nodes.py` | Новый `apply_edits_node` между `plan` и `render`. Если `state.options.user_edits` пуст — no-op. Иначе `plan' = apply(plan, edits)`. |
| `backend/src/masker/graph/build.py` | Ребро `plan → apply_edits → render`. |
| `backend/src/api/routers/runs.py` | Новый `POST /api/runs/{tid}/edits`. Тело — список правок в форме, идентичной `edits.py`. Сервис: создать **новый** прогон через `start_run(...)` с `user_edits=parent_edits + delta`. Возвращает новый `thread_id` + отчёт (или waiting-состояние). |
| `backend/src/api/services/runs_service.py::apply_edits` | Найти родительский прогон в SQL, взять его `object_name` и `options`, добавить delta правок, `start_run(..., fresh=False)` — идемпотентно, `thread_id_for` уже даст новый id, старый цел. |
| `backend/src/api/schemas/edits.py` | **NEW.** Pydantic под правки. |
| `backend/tests/masker/graph/test_apply_edits.py` | **NEW.** unmask/add/change. |
| `backend/tests/api/test_runs_edits.py` | **NEW.** Прогон → PATCH правок → новый thread_id, отчёт не содержит снятой сущности в highlights. |
| `docs/plans/feat-highlight-coords-edits.md` | Этот файл. |

## Операции правок — семантика

1. **`unmask_ref(ref)`** — исключает конкретный `Replacement`. Работает на
   любом `ref`, включая критичные (осознанное решение, но с флагом
   `override_critical=true` в теле — иначе `422`).
2. **`unmask_profile(profile_id)`** — исключает все `Replacement`, у которых
   `profile_id` совпадает.
3. **`unmask_type(entity_type)`** — исключает все с `entity.type == type`.
   Не работает на CRITICAL_TYPES без `override_critical`.
4. **`add_mask(page, bbox_normalized, entity_type, marker?)`** — добавляет
   ручную маску. Внутри графа кладётся как искусственный `Segment`
   `origin="user"` с якорем `("page", n, "user", x0, y0, x1, y1)` (в pt,
   пересчёт из normalized через размеры страницы **артефакта**) и
   `Entity(source=Source.USER, level=CONFIRMED)`; дальше `PlanAgent` строит
   `Replacement` штатно.
5. **`change_type(ref, new_type)`** — только для не-критичных: детектор
   переклассифицировал, маркер строится от нового типа.

**Критичный тип защищён.** Инвариант «судья не спрашивает про критичное»
превращается в «фронт не снимает критичное без `override_critical=true`»;
без флага сервис возвращает `422` c `reason="critical_requires_override"`.

## Инварианты

1. **Первый прогон не мутируется.** Правки всегда создают новый `thread_id`
   и новую строку в `runs`. Отчёт первого прогона неизменен.
2. **Идемпотентность правок.** Тот же список правок в том же порядке даёт
   тот же `thread_id`. `canonical()` сортирует правки по стабильному ключу.
3. **`user_edits` не могут ломать граф.** `apply_edits_node` валидирует
   `ref`/`profile_id`/`type` относительно `plan` до применения; неизвестный
   `ref` — `ValueError` (превращается в `RunFailedError`).
4. **Ссылочная целостность.** `ref`, отданные во фронт, стабильны в
   пределах документа: `EntityIndex` уже строит их детерминированно.
   `unmask_ref("E17")` из первого прогона обязан адресовать ту же сущность
   в родительском плане второго прогона — то есть **правки применяются к
   исходному плану до фильтрации**, а не к плану предыдущего прогона.
5. **Валидация после правок.** `ValidateAgent` не отключается: снятая
   вручную маска на критичном типе всё равно попадает в `residual`
   секцию отчёта как «сознательное решение», чтобы это было видно.

## Порядок работ

### К1 — highlights только по существующему плану (без правок)
- `highlights/*`, интеграция в `report_node`, `HighlightsOut`;
- `test_build.py`;
- `pytest backend/tests/masker/highlights/`.

Приёмка: `report["highlights"]` есть у любого прошедшего прогона.

### К2 — модель правок и `apply_edits_node`
- `graph/edits.py` + узел;
- сериализация в state;
- `test_apply_edits.py`.

Приёмка: юниты зелёные, `make gate` не сломался (пустой список правок =
no-op).

### К3 — API-роут `/edits` и сервис
- `runs.py`, `runs_service.apply_edits`;
- `test_runs_edits.py`.

Приёмка: PATCH с правками возвращает новый `thread_id`, старый прогон цел.

### К4 — критичные типы и `override_critical`
- Валидация в сервисе;
- сообщение с `critical_requires_override`;
- e2e тест: попытка снять ИНН без флага → 422.

Приёмка: тест `test_runs_edits.py::test_critical_requires_override`.

### К5 — «добавить пропущенное»
- `add_mask` целиком;
- тест: `POST /edits` c `add_mask` → в новом прогоне маска есть в
  `highlights` и в артефакте.

Приёмка: `test_runs_edits.py::test_add_mask`.

## Возможные грабли

- **Артефакт для координат ≠ исходный PDF.** Размеры страниц после
  квантизации ширины (`_quantize_erase_rect`, `pdf_render.py`) могут
  измениться на доли pt. Читаем размеры **из готового артефакта**, а не из
  source-документа.
- **Docx-preview PDF рендерит через LibreOffice в контейнере.** Если
  контейнер не поднят локально — highlight-координат для docx не будет.
  Не блокер плана: за отсутствие preview отвечает `render_node`, `highlights`
  просто вернёт пустой список для страниц, которых нет.
- **`add_mask` в OCR-режиме.** Пользователь может обвести на канвасе
  область, где OCR ничего не увидел. Тогда `Segment("", ...)` — пусто.
  Правило: `add_mask` требует `text` в теле правки (юзер видел, что писал)
  либо `text_from_ocr=true` — сервис вызовет OCR на bbox и заберёт распознанное.
- **`unmask_profile` + автоматически найденный второй профиль.** Если после
  повторной детекции профилей стало больше или id сдвинулись — правка
  сломается. Решение: `profile_id` в правке — не тот, что вернулся из
  первого прогона, а **строковый ключ профиля** (см. `ProfileAgent`), который
  стабилен между прогонами при том же документе. Проверить, что такой
  стабильный ключ уже есть; если нет — вынести в отдельный микрошаг.
- **Отсутствие обратной совместимости.** `HighlightsOut` был заглушкой в
  feat-api-runs; здесь мы её реализуем. Фронт увидит непустое поле — это ок,
  контракт формы не меняется.

## Определение готовности

1. `make gate` зелёный.
2. Все пять шагов К1–К5 закрыты.
3. `report["highlights"]` содержит непустой список на любом прогоне из
   fixtures.
4. `PATCH /api/runs/{tid}/edits` c простой правкой возвращает новый
   `thread_id` и отчёт с изменённым `highlights`.
5. Попытка снять критичный тип без `override_critical` — `422`.
6. Ручной smoke: провести один документ через фронт (или `curl`), сделать
   правку, увидеть новую версию в `GET /runs`. Приложить в PR-описание.
