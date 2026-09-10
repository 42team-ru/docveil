# Хендофф: O4 — Рендер скан-страниц (09.09.2026)

Четвёртая подзадача плана `docs/plans/T2.3-ocr-paddleocr.md`. Добавлен путь
рендера для OCR-сегментов: стирание пикселей, маркер поверх, невидимый
текстовый слой.

**Ветка:** `feat/ocr-scan-render` (от `feat/ocr-scan-ingest`).

**Состояние: ворота зелёные.**

---

## 1. Что закрыто по приёмке O4

| Пункт приёмки | Статус |
|---|---|
| OCR-локатор не крашит `render_pdf_redacted` | ✅ |
| Пиксельный слой стирается (`PDF_REDACT_IMAGE_PIXELS`) для скан-страниц | ✅ |
| Маркер вставляется поверх эрейз-прямоугольника | ✅ |
| Невидимый текстовый слой (`render_mode=3`) с маркером вместо исходного текста | ✅ |
| `render_pdf_preview` — OCR-сущности подсвечиваются через `add_highlight_annot` | ✅ |
| `compute_erase_geometry` / `compute_label_geometry` — OCR-локаторы пропускаются без краша | ✅ |
| Два прогона на одном входе дают побайтово одинаковый вывод (`no_new_id=1`) | ✅ |
| Стиль `blackbox` корректно работает для OCR-страниц | ✅ |
| Смешанный PDF: текстовые страницы — прежний путь, OCR-страницы — новый | ✅ |
| Все существующие тесты не сломаны (83 render-теста) | ✅ |

---

## 2. Что появилось в коде

**`backend/src/masker/render/pdf_render.py`** (правки):

- `_is_ocr_locator(locator)` — проверяет `len == 7 and locator[2] == "ocr"`.
- `_parse_ocr_locator(locator)` — распаковывает `(page_num, x0, y0, x1, y1)` в pt
  (делит на 100).
- `_entity_rect_ocr(seg_rect, seg_text_len, entity_start, entity_end)` — строит
  `Rect` сущности линейной интерполяцией по ширине bbox сегмента. Моноширинное
  приближение достаточно для OCR-строк: маркер вписывается в стёртую полосу,
  а не в каждый глиф.
- `_OcrPageJob` — dataclass аналог `_PageJob` для OCR-локаторов: хранит
  `replacement`, `seg_rect`, `entity_rect`.
- `_insert_invisible_ocr_layer(page, jobs)` — для каждого OCR-задания вставляет
  `replacement.marker` через `page.insert_text(..., render_mode=3, fontsize=1)`.
  Шрифт `DejaVuSans`, позиция — нижний-левый угол `entity_rect`. Так copy-paste
  из результата даёт маркер, а не исходный OCR-текст.
- `render_pdf_redacted()`: две параллельные очереди `by_page` (текст) и
  `ocr_by_page` (OCR). OCR-страницы: `apply_redactions(images=PDF_REDACT_IMAGE_PIXELS)`,
  затем сбор кандидатов для лестницы M4 в общий `candidates_by_group` /
  `pending_labels`. Второй проход (label placement) — тот же `_place_label_fixed`.
  Невидимый слой вставляется после обоих проходов, перед `doc.save()`.
- `doc.save(... no_new_id=1)` — предотвращает генерацию нового `/ID[id1 id2]`
  при каждом сохранении; без этого флага два идентичных прогона давали разные
  байты из-за `id2` (modification ID) с временно́й меткой.
- `render_pdf_preview()` — добавлена ветка OCR: `_entity_rect_ocr` по bbox
  сегмента, `add_highlight_annot(rect)`.
- `compute_erase_geometry()`, `compute_label_geometry()` — пропускают OCR-локаторы
  (`_is_ocr_locator` check перед `_parse_locator`).

**`backend/tests/masker/render/test_scan_render.py`** (новый, 6 тестов):

- `test_scan_render_wipes_text_layer` — текстовый слой результата не содержит ИНН.
- `test_scan_render_marker_in_invisible_layer` — текстовый слой содержит маркер.
- `test_scan_render_idempotent` — два прогона побайтово равны.
- `test_scan_render_outcome_has_erase_regions` — `RenderOutcome.replacements[0]`
  имеет ненулевые `erase_regions`.
- `test_scan_render_blackbox` — стиль `blackbox` не крашится и стирает ИНН.
- `test_scan_render_mixed_pdf` — смешанный PDF рендерится без ошибок.

---

## 3. Что сознательно НЕ делали в O4

- **`count_highlight_overlaps` для OCR-сегментов** — функция пропускает
  OCR-замены (нет символьных боксов для сравнения). Метрика для OCR-страниц
  реализуется в O5 через отдельный механизм (pixel-diff на синтетическом корпусе).
- **`compute_erase_geometry` / `compute_label_geometry` для OCR** — возвращают
  только геометрию текстовых сегментов. Сертификат обезличивания для OCR-страниц
  опирается на `test_scan_render_wipes_text_layer`, а не на функции сертификата.
- **Квантование ширины (`_quantize_erase_rect`) для OCR** — не применяется:
  bbox OCR-строки и без того достаточно широк (≥ 12 pt в реальных документах),
  а само квантование решает задачу утечки через ширину символьных боксов — у
  OCR нет этого канала.

---

## 4. Проверка

```
cd backend
./scripts/gate.sh
pytest tests/masker/render/test_scan_render.py -v
```

---

## 5. Что дальше — O5

Синтетический корпус сканов, метрики и ворота:
- `scripts/gen_scan_fixtures.py` — генератор `scan_synth_0{1,2,3}.pdf` из
  существующих `contract_pdf_*.pdf`.
- `eval.py` — порог `scan_critical_recall == 1.0` на скан-корпусе.
- Обновить `AGENTS.md`, `TASKS.md`, `ARCHITECTURE.md`.
