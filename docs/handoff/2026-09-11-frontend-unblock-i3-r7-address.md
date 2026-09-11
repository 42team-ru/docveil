# Хендофф: батч 2026-09-11 — фронт-разблокировка, И3, Р7, адреса

## Что сделано

Четыре задачи, три PR, все узкие тесты зелёные (128 passed, 3 skipped e2e).

| Задача | Ветка | PR | Статус |
|---|---|---|---|
| Задача 1 — API-схема отчёта | `feat/api-schema-facts` | [#34](https://github.com/42team-ru/triema-masker/pull/34) | ready |
| Задача 3 — Р7 верификатор address | `feat/r7-verifier-address` | [#35](https://github.com/42team-ru/triema-masker/pull/35) | ready |
| Задача 4 + Задача 2 (И3) + Postman | `feat/i3-custom-types-maxima` | [#36](https://github.com/42team-ru/triema-masker/pull/36) | ready |

---

## Задача 1 — API-схема отчёта (блокировала фронт, закрыта)

`ContractSummaryOut` отдавал 11 полей, `export_summary()` писал 21+. Добавлены 8
типизированных Out-моделей (`ContractFactOut`, `MoneyFactOut`, `PaymentFactOut`,
`DeliveryFactOut`, `DocumentKindOut` и вспомогательные), `ContractSummaryOut` расширена
до полного зеркала `masker/summary/model.py`, в `ReportOut` добавлена `telemetry`.
`core.json` пересобран; **`yarn orval` нужно запустить руками** после `yarn install`
во фронте.

**Изменённые файлы:**
- `backend/src/api/schemas/report.py` — 8 новых Out-моделей + расширения `ContractSummaryOut` и `ReportOut`
- `frontend/src/shared/api/schemas/core.json` — пересобран `dump_openapi.py`

---

## Задача 2 (И3) — программа максимум по пользовательским типам

### 2.1 Валидация описаний
`CompileRequest.descriptions` — trim + min 8 символов + max 1000 → 422 на пустое,
пробельное, «паспорт» (7 символов).

### 2.2 Preview для `regex_llm_filter`
`_entities_for_spec()` в `preview.py` больше не кидает `ValueError` для этого kind —
preview показывает кандидатов регулярки без LLM-фильтрации (явное упрощение, достаточно
для «что найдёт паттерн»).

### 2.3 Машиночитаемый код ошибки
`FailReason` (str-Enum) добавлен в `api/schemas/custom_types.py`:
`empty_description`, `too_short`, `too_long`, `llm_unavailable`, `invalid_regex`,
`redos_pattern`, `regex_too_long`, `empty_match`, `cannot_compile`,
`ask_rounds_exhausted`, `preview_error`.

`FailedTypeOut` получил `code: FailReason = FailReason.cannot_compile`.
`CannotCompileOutcome` в `compiler.py` получил `code: str`; три точки выставляют
конкретный код: `llm_unavailable` (LLMError), `ask_rounds_exhausted` (MAX_ASK_ROUNDS),
`cannot_compile` (retry failure). Граф сохраняет код в state, сервис маппит в `FailReason`.

### 2.4 Примеры отказов в промпте
`prompt.py` версии 3: три примера с правильными JSON-ответами (слишком общее →
`cannot_compile`, неоднозначность «ФИО кроме подписи» → `ask`, «даты» → `ask`),
явный лимит паттерна 200 символов, запрет ReDOS с примером `(\\d+)+`.

### Новые тесты (13 штук)
- `test_custom_types_schema.py` — граничные значения длины, trim, `FailReason`
- `test_compiler.py` — коды `llm_unavailable`, `ask_rounds_exhausted`, `cannot_compile`
- `test_preview.py` — `regex_llm_filter` не падает, возвращает совпадения

**Изменённые файлы:**
- `backend/src/api/schemas/custom_types.py` — `FailReason`, `FailedTypeOut.code`, валидатор описаний
- `backend/src/api/services/custom_types_service.py` — маппинг кода в `FailReason`
- `backend/src/masker/customtypes/compiler.py` — `CannotCompileOutcome.code`
- `backend/src/masker/customtypes/graph.py` — `item["code"]` в state
- `backend/src/masker/customtypes/preview.py` — ветка `regex_llm_filter`
- `backend/src/masker/customtypes/prompt.py` — примеры отказов, `PROMPT_VERSION = "3"`
- `backend/tests/api/test_custom_types_schema.py`
- `backend/tests/masker/customtypes/test_compiler.py`
- `backend/tests/masker/customtypes/test_preview.py`

---

## Задача 3 (Р7) — верификатор второго прохода для адресов

`VERIFIER_TYPES` расширен до `{"person", "org_name", "address"}`.
`find_weak_signal_spans()` скармливает LLM слабые сигналы: 6-значные числа
(потенциальный индекс, `_POSTAL_INDEX_RE`) и обрывки с «обл.»/«г.»/«ул.»/«пр-т»
(`_ADDRESS_FRAGMENT_RE`). Кандидаты — только спаны, не покрытые `baseline_entities`.

Побочный эффект: часть обрывков из Задачи 4, которые первый проход отбрасывает,
верификатор может восстановить как целый адрес в окне ±160 символов вокруг сигнала.

**Изменённые файлы:**
- `backend/src/masker/detect/verifier.py`
- `backend/tests/masker/detect/test_verifier.py`

---

## Задача 4 — адреса-обрывки и «Зои»

**Проблема:** на `edukirovsk-2018-659372.pdf` 289 адресов, среди них обрывки
`'102400'`, `'обл., 184600'`, `'Мурманская обл., 184209'`. Плюс `person 'Зои'`
внутри «улица Зои Космодемьянской».

`_is_sufficient()` ужесточена — голый индекс больше не адрес; требуется
`settlement+index` ИЛИ `settlement+(street|building)`.

`_STREET_MARKERS` в `persons.py` дополнен полными формами («улица», «проспект»,
«переулок», «набережная», «шоссе», «бульвар», «тупик», «квартал», «площадь»,
«аллея», «линия», «проезд», предложные «переулке», «улице», «проспекте») —
`preceded_by_address_marker()` теперь работает и с полной формой.

**Изменённые файлы:**
- `backend/src/masker/detect/address.py` — `_is_sufficient()`
- `backend/src/masker/detect/persons.py` — `_STREET_MARKERS`
- `backend/tests/masker/detect/test_address.py` — 2 новых теста

---

## Postman и документация

- `postman/triema-masker.postman_collection.json` — новая папка «Задача 1 — Схема
  отчёта» (5 шагов: login → upload → run → poll → GET report с проверкой всех новых
  полей `*_fact`, `telemetry`) + 7 И3-сценариев в «Custom data types» (негативные
  кейсы валидации, happy path, ответ на вопрос, `cannot_compile`, `regex_llm_filter`
  preview)
- `docs/plans/2026-09-11-frontend-unblock-i3-r7-address.md` — план батча с критериями приёмки

---

## Что нужно сделать вручную перед мержем

1. **`yarn install && yarn orval`** в `frontend/` после мержа PR #34.
2. **`make gate`** — полные ворота запускает только ведущий, после слияния всех трёх PR.
3. Postman-коллекция с живым GigaChat — папки «Задача 1» и «Custom data types».

## Что не сделано (намеренно, за рамками батча)

- `CustomTypeError.code` в `typeconfig.py` — 30+ `raise CustomTypeError(...)` не
  получили коды (`invalid_regex`, `redos_pattern` и т.д.); сервис при `"failed"`
  без кода молча ставит `cannot_compile` как fallback. Продолжение — отдельная задача.
- Постоянная сшивка в `find_weak_signal_spans()` — кейс «индекс уже замаскирован,
  улица нет» требует дополнительной логики.
- `yarn orval` в CI — не автоматизировано.
