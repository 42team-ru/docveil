# План: bbox-координаты сущностей и bbox-based правки (delta поверх feat/union)

## Контекст

Цикл правок от оператора уже реализован в feat/union (смержен в
`feat/ocr-scan-render` коммитом 0c8c7a3):

- Второй interrupt графа `ask_review` (узел `masker.graph.review`), новое
  ребро `report → ask_review → apply_review_edits → plan`.
- Статус `awaiting_review`, роуты `GET/POST /api/runs/{id}/review`.
- Схема `ReviewEdits`: `decisions: {ref → mask|keep}`, `type_overrides:
  {ref → type}`, `manual: [{type, text}]` — text-based, **без bbox**.

Значит цикл правок целиком, `unmask_ref` через `decisions`, смена типа
через `type_overrides`, добавление пропущенного через `manual` (по тексту)
— **уже есть**.

Чего в feat/union нет:

1. **Координаты сущностей в отчёте для UI-подсветки.** `EntityRecordOut`
   несёт `anchor.locator` в исходной геометрии документа (символьный
   диапазон для docx/xlsx, char-range или (page, ocr, bbox) для pdf), но
   не нормализованный bbox готового артефакта — а фронту нужны координаты
   для того самого PDF, что он рендерит.
2. **bbox-based `add_mask`.** `ManualEntityIn` принимает только
   `(type, text)`. Если оператор обвёл на канвасе область — движок не
   поймёт, куда именно её вставить (текстовый поиск может промазать или
   найти несколько мест).

Этот план **закрывает ровно две дырки** — координаты сущностей в отчёте и
опциональный `region` в `manual`.

## Ветка

```
git switch -c feat/highlight-coords-edits  # от feat/ocr-scan-render
```

## Формат координат в отчёте

### Расширение `EntityRecordOut`

Новое поле `regions: list[BboxRegionOut] = []`:

```python
class BboxRegionOut(BaseModel):
    """Одна прямоугольная область сущности на странице PDF-артефакта.

    Координаты нормализованы 0..1 по размерам страницы готового
    ``masked_highlight.pdf`` (не исходного документа) — фронт умножит на
    физический размер canvas в любом zoom без пересчёта. Одна сущность на
    одной странице — один регион; сущность, попавшая на две страницы
    (перенос), даёт две записи с разными ``page``.
    """
    page: int       # 0-based
    x0: float       # 0..1
    y0: float
    x1: float
    y1: float
```

Поле — пустой список для форматов, где артефакт не PDF (сегодня — всех
docx/xlsx до тех пор, пока `render/docx_preview.py` не сгенерирует PDF-
preview; для картинки после мержа feat-image-ingest — заполняется, потому
что промежуточный артефакт всё равно PDF).

### Секция `report.pages`

Новое поле в `SummaryOut` (или в `ReportOut` — выбрать одно место):

```python
class PageInfoOut(BaseModel):
    page: int
    width_pt: float
    height_pt: float
```

Список размеров страниц готового артефакта. Фронт сравнивает `page` в
`BboxRegionOut` и в `PageInfoOut` — это единственный маппинг, который ему
нужен, кроме собственно рендера PDF в канвас.

## bbox-based `manual`

### Расширение `ManualEntityIn`

Опциональное поле `region: BboxRegionIn | None = None`:

```python
class BboxRegionIn(BaseModel):
    page: int
    x0: float       # 0..1
    y0: float
    x1: float
    y1: float
```

Семантика:
- Если `region is None` — старое поведение (текстовый поиск в документе).
- Если `region is not None` — сервер создаёт искусственный `Segment` с
  `origin="user"` и якорем `("page", n, "user", x0_pt, y0_pt, x1_pt, y1_pt)`
  (координаты **денормализуются** в pt по размерам страницы **артефакта**),
  `Entity(source=Source.USER, level=CONFIRMED)`, дальше `PlanAgent`
  обрабатывает штатно. `text` в теле правки всё равно обязателен — движок
  использует его как значение сущности для сборки группы согласованности
  (иначе два одинаковых «Иванов» не сойдутся в один маркер).

Инвариант: `text` + `region` = «текст точно этот, находится ровно здесь».
Никакого текстового поиска и никакого OCR-извлечения — фронт видел, что
пишет.

## Раскладка изменений

| Файл | Действие |
|---|---|
| `backend/src/masker/highlights/__init__.py` | **NEW.** `build_regions_by_ref(plan, artifact_pdf_path) -> dict[str, list[BboxRegion]]`. Чистая функция, тесты изолированно. |
| `backend/src/masker/highlights/page_dims.py` | **NEW.** Читает `width_pt/height_pt` каждой страницы готового артефакта через PyMuPDF. |
| `backend/src/masker/highlights/coords.py` | **NEW.** Union `paint_regions` каждого `Replacement` → нормализация по размерам страницы артефакта. |
| `backend/src/masker/graph/nodes.py::_build_report_dict` (или где формируется `report`) | Дополнить `entities[]` полем `regions`, добавить `report["pages"]`. |
| `backend/src/api/schemas/report.py::EntityRecordOut` | Добавить `regions: list[BboxRegionOut] = []`. |
| `backend/src/api/schemas/report.py::PiiEntryOut` | Наследует поле от `EntityRecordOut`. |
| `backend/src/api/schemas/report.py` | Новые `BboxRegionOut`, `PageInfoOut`. `ReportOut` (или `SummaryOut`) получает `pages: list[PageInfoOut]`. |
| `backend/src/api/schemas/run.py::ManualEntityIn` | Опциональное `region: BboxRegionIn = None`. |
| `backend/src/api/schemas/run.py::BboxRegionIn` | **NEW.** |
| `backend/src/masker/graph/review.py::parse_review_edits` | Обработка `manual[].region`: если задан — денормализация pt через размеры страниц артефакта (`highlights.page_dims`), сборка искусственного сегмента `origin="user"`. Артефакт-файл читается из `state["artifacts"]` (уже там лежит). |
| `backend/tests/masker/highlights/test_build.py` | **NEW.** Юниты: одна сущность = один регион на странице, многострочная = один union-регион, нормализация 0..1, разбивка при переносе. |
| `backend/tests/masker/graph/test_review_region.py` | **NEW.** `manual` c `region` создаёт сегмент с `origin="user"`; повторный прогон включает в `report.entities[]` сущность с этим регионом. |
| `backend/tests/api/test_runs_report.py` | **NEW.** После завершения прогона `GET /runs/{id}/report` содержит `entities[].regions` и `pages[]`. |
| `docs/plans/feat-highlight-coords-edits.md` | Этот файл. |

## Инварианты

1. **Координаты — по артефакту, не по source.** Размеры страниц читаются
   из готового `masked_highlight.pdf`, потому что после квантизации ширины
   (`_quantize_erase_rect`, `pdf_render.py`) страницы могут чуть-чуть
   отличаться от исходного PDF.
2. **`regions: []` для docx/xlsx без PDF-preview.** Не выдумывать
   координаты для форматов, для которых нет геометрии. Пустой список —
   валидный ответ.
3. **`manual[].region` требует `text`.** Иначе групповая согласованность
   маркеров ломается. 422 без text.
4. **Денормализация в pt — по артефакту первого прогона.** Артефакт для
   `ask_review` уже собран, файл на диске; `review.py` читает размеры из
   него. Если артефакт удалён (не должно, но) — сервис отвечает 409.
5. **`origin="user"` — новый допустимый строковый тег `Segment.origin`.**
   Проверить, что все потребители `origin` (детекция, план, рендер,
   отчёт) видели `"text"`/`"ocr"`/`"user"` и не падают на новом. Скорее
   всего они `origin` не смотрят — но проверить явно.
6. **Ссылочная целостность.** `ref` в `decisions`/`type_overrides` уже
   стабильны в рамках прогона (это ссылки на `Replacement`). Не трогаем.

## Порядок работ

Три инкремента, каждый — самостоятельно проходит `make gate`.

### К1 — координаты сущностей в отчёте
- `highlights/*`, интеграция в `_build_report_dict`, схемы `BboxRegionOut`
  + `PageInfoOut`.
- Юниты + API-тест.

Приёмка: `test_build.py`, `test_runs_report.py`.

### К2 — bbox-based manual
- `BboxRegionIn`, расширение `ManualEntityIn`, поддержка в
  `parse_review_edits`.
- Юнит + review-round тест.

Приёмка: `test_review_region.py`.

### К3 — валидация
- 422 без `text` при заданном `region`.
- 422 если `region` вне 0..1.
- Тесты.

Приёмка: `test_runs_review.py` (или где живут негативные кейсы review).

## Возможные грабли

- **Артефакт `masked_highlight.pdf` может отсутствовать.** Если пользователь
  запросил только `blackbox` — highlight-варианта нет. Тогда `regions`
  строятся по `masked_black.pdf` (координаты идентичны — одни и те же
  `paint_regions`). Правило: берём первый попавшийся PDF-артефакт в
  `state["artifacts"]`. Если ни одного PDF нет — `regions: []`.
- **`origin="user"` и валидатор.** `ValidateAgent` не должен считать
  добавленную вручную маску утечкой (её же не было в исходнике). Проверить,
  что таксономия `Leak` не срабатывает на `Segment.origin="user"`.
- **Порядок правок оператора.** Если оператор в одном раунде и снял маску,
  и добавил по bbox — движок обрабатывает всё в одном `apply_review_edits`:
  сначала `decisions` (снимает), потом `manual` (добавляет), потом
  `type_overrides`. Порядок фиксирован для детерминизма.
- **Размер страниц докс-превью.** Если docx-preview не собран (нет
  LibreOffice), артефакт-PDF не появится — тогда `pages: []` и все
  `regions: []`. Не блокер плана.

## Определение готовности

1. `make gate` зелёный.
2. Три инкремента закрыты, тесты в CI.
3. `GET /api/runs/{id}/report` возвращает `entities[].regions` и `pages[]`
   для PDF-прогона.
4. `POST /api/runs/{id}/review` c `manual[].region` создаёт правильную
   маску в новом раунде.
5. Ручной smoke: прогон → координаты → отрисовать в canvas → проверить
   геометрию глазами.
