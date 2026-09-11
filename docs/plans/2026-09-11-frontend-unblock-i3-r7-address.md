# Батч из 4 задач: разблокировать фронт, И3, Р7, адреса-обрывки

## Context

Тимлид дал батч из четырёх задач разного веса. Общая мотивация:

1. **Задача 1 (API-схемы отчёта)** — блокирует фронт: В11 и К5 не могут двигаться, потому что `ContractSummaryOut` в `backend/src/api/schemas/report.py:246-258` отдаёт 11 плоских полей, а `export_summary()` уже пишет в `report.json` 21 поле с `*_fact`, `brief_summary`, `document_kind`, плюс не декларирована `telemetry` в `ReportOut`. Внутренние pydantic-модели уже готовы в `backend/src/masker/summary/model.py`, нужно только зеркалить их в API-схему и перегенерировать снимок openapi для фронта.

2. **Задача 2 (И3, пользовательские типы)** — программа максимум по трём кускам приёмки. Функциональный костяк есть (LangGraph компилятора, роутер `/custom_types/compile`+`/answers`, все kind в `typeconfig.py`, `GlinerDetector` с ролевыми описаниями после Р10), но точечный аудит нашёл конкретные дыры (см. список).

3. **Задача 3 (Р7 верификатор)** — верификатор уже полный и включён в пайплайн (`backend/src/masker/detect/verifier.py`, 623 строки, strict-schema, попадает в `report.json`), но типы ограничены `{"person","org_name"}`. Пользователь выбрал расширить его на адреса — это заодно поможет и Задаче 4 как второй проход.

4. **Задача 4 (адреса-обрывки)** — конкретный дефект качества: на `fixtures/real-contracts/open-contracts/edukirovsk-2018-659372.pdf` 289 адресов, среди них обрывки `'102400'`, `'обл., 184600'`, `'Мурманская обл., 184209'`. Не утечка (маскируется лишнее), но сигнал, что склейка работает не до конца. Плюс кейс `person 'Зои'` внутри «улица Зои Космодемьянской» — защита `preceded_by_address_marker()` не сработала, потому что в `_STREET_MARKERS` только сокращения.

Ответы пользователя на развилки:
- **Задача 1** — строгие типизированные Out-модели (1-в-1 c внутренними).
- **Задача 3** — добавить `address` в верификатор.
- **Задача 4** — двухшаговый подход: сначала пытаемся склеить, если не проходит `_is_sufficient` — отбрасываем.
- **Задача 2** — программа максимум по всем выявленным пробелам.

## Задача 1. API-схема отчёта (30 минут)

**Что делать.**

1. `backend/src/api/schemas/report.py` — завести Out-модели 1-в-1 с `backend/src/masker/summary/model.py`:
   - `FactAnchorOut` (page, box) — под `FactAnchor`
   - `FactAlternativeOut` — под `FactAlternative`
   - `ContractFactOut` — под `ContractFact` (value, source_quote, anchors, source, status, alternatives)
   - `MoneyFactOut(ContractFactOut)` — currency, vat, purpose
   - `PaymentStageOut` — под `PaymentStage`
   - `PaymentFactOut(ContractFactOut)` — stages
   - `DeliveryFactOut(ContractFactOut)` — object_or_batch, onset_event, days, day_kind
   - `DocumentKindOut` — status, genre, confidence, source
2. Расширить `ContractSummaryOut` полями (все опциональные, с дефолтами `None`/`[]`):
   - `customer_fact`, `supplier_fact`, `procurement_regime`, `contract_number_fact` → `ContractFactOut`
   - `federal_law_facts: list[ContractFactOut]`
   - `contract_amount_fact: MoneyFactOut`
   - `payment_facts: list[PaymentFactOut]`
   - `delivery_facts: list[DeliveryFactOut]`
   - `brief_summary: str | None`
   - `document_kind: DocumentKindOut`
3. В `ReportOut` добавить `telemetry: TelemetryOut | None = None`. Модель `TelemetryOut` — с `events: list[EventOut]`, `llm: LlmTelemetryOut`, `runtime: RuntimeTelemetryOut`. Смотреть форму из `backend/src/masker/telemetry.py:183-208`.
4. В тесте `backend/tests/masker/graph/test_report_node.py:_REFERENCE_KEYS` (строки 22-59) добавить `telemetry` — по факту он уже в отчёте, но эталон об этом не знает (агент это отметил как баг эталона).
5. Пересобрать снимок фронта:
   ```bash
   cd backend && .venv/bin/python scripts/dump_openapi.py
   cd frontend && yarn orval
   ```

**Ключевые файлы.**
- `backend/src/api/schemas/report.py` (расширить)
- `backend/src/masker/summary/model.py` (не менять, только смотреть)
- `backend/src/masker/telemetry.py` (не менять, смотреть форму)
- `backend/scripts/dump_openapi.py`
- `frontend/src/shared/api/schemas/core.json` (регенерируется)
- `backend/tests/masker/graph/test_report_node.py` (правка `_REFERENCE_KEYS`)

**Verify.**
- `pytest tests/api/test_runs_report.py tests/masker/graph/test_report_node.py -x`
- Postman-сценарий через живую GigaChat (см. раздел «Postman»)
- Ручной запуск бекенда, `curl http://localhost:8000/openapi.json | jq '.components.schemas.ContractSummaryOut'` — все новые поля описаны.

## Задача 2. И3 — программа максимум (пробелы аудита)

### 2.1 Валидация входного описания на этапе схемы

**Файлы.** `backend/src/api/schemas/custom_types.py:177-178`

- В `CompileRequest.descriptions` завести элементы как `DescriptionItemIn` c валидатором:
  - `text: str = Field(min_length=8, max_length=1000)` (эмпирически 8 символов — минимум чтобы фраза «даты подписания» прошла, а `" "` — нет)
  - Trim в валидаторе; пустая строка после trim → 422 с локализованным сообщением
- Тесты в `backend/tests/api/test_custom_types_schema.py`: пустое, только пробелы, 7 символов, 1001 символ.

### 2.2 Preview для `regex_llm_filter` (КРИТИЧНО)

**Файлы.** `backend/src/masker/customtypes/preview.py:56-66`

Сейчас `_entities_for_spec()` кидает `ValueError` на `kind="regex_llm_filter"`. Это баг: компилятор эту спеку возвращает, `preview_node` пытается прогнать — падение.

- Добавить ветку `if spec.kind == "regex_llm_filter":` — прогонять `ConfigDetector` (regex+context) и результат прогонять через `LlmFilterDetector` из `backend/src/masker/detect/` (тот же путь, что в основном пайплайне).
- Тест в `backend/tests/masker/customtypes/test_preview.py` (создать при отсутствии).

### 2.3 Машиночитаемый код ошибки

**Файлы.**
- `backend/src/api/schemas/custom_types.py` (`FailedTypeOut`)
- `backend/src/masker/customtypes/compiler.py:277-288`
- `backend/src/masker/typeconfig.py`

- Завести `FailReason` (str-Enum): `"empty_description"`, `"too_short"`, `"too_long"`, `"llm_unavailable"`, `"invalid_regex"`, `"redos_pattern"`, `"regex_too_long"`, `"empty_match"`, `"cannot_compile"`, `"ask_rounds_exhausted"`, `"preview_error"`.
- В `FailedTypeOut` добавить `code: FailReason` (обязательное).
- `CustomTypeError` получает атрибут `code: FailReason`; каждый `raise CustomTypeError(...)` в `typeconfig.py` пробрасывает конкретный код.
- `CannotCompileOutcome(reason, code)` — код проставляется в местах `compiler.py:280` (`llm_unavailable`), `compiler.py:283-287` (`ask_rounds_exhausted`), `compiler.py:243-244` (`cannot_compile`).
- Сервис `backend/src/api/services/custom_types_service.py` мапит внутренний код → `FailReason`.
- Тесты в `backend/tests/masker/test_compiler.py` (проверить, что код проставляется в правильных ветках).

### 2.4 Примеры плохих входов в промпте компилятора

**Файлы.** `backend/src/masker/customtypes/prompt.py:75-111`

- Добавить блок «Примеры отказа» с 3 ситуациями:
  - «замазать всё что может быть плохо» → `cannot_compile` с объяснением, что описание слишком общее
  - «даты» (короче 8 символов после валидации, но всё же дошло) → `ask` с уточнением, какие именно даты
  - Противоречивое: «маскируй все ФИО, кроме тех, что в подписи» → `ask` с уточнением
- Явно записать лимит длины регулярки (200 символов, `MAX_PATTERN_LEN`) и запрет вложенных квантификаторов с одним примером (`(a+)+`).

### 2.5 Тесты

- `backend/tests/api/test_custom_types_schema.py` — граничные значения длины, trim.
- `backend/tests/masker/test_compiler.py` — код ошибки в `CannotCompileOutcome`.
- `backend/tests/masker/customtypes/test_preview.py` — `regex_llm_filter`, `regex+context`, `gliner_label`, `gliner_structure`.
- `backend/tests/api/test_custom_types_router.py` — проверка, что `FailedTypeOut.code` возвращается на пустое описание.

**Проверять дёшево:**
```bash
cd backend && .venv/bin/python scripts/check_doc.py fixtures/labeled/<файл> --type <свой_тип>
```
2 секунды вместо прогона корпуса.

## Задача 3. Р7 — расширить верификатор до address

**Файлы.** `backend/src/masker/detect/verifier.py:130-159` (`_RESPONSE_SCHEMA`), 110-119 (`_SYSTEM_PROMPT`), `find_weak_signal_spans()`.

1. `_RESPONSE_SCHEMA`: расширить enum `type` до `["org_name", "person", "address"]`.
2. `VERIFIER_TYPES = {"person", "org_name", "address"}`.
3. `_SYSTEM_PROMPT`: добавить блок про адреса — что считать полным адресом (индекс+регион+улица+дом; допустимы кавычки и переносы строк), что цитировать буквально.
4. `find_weak_signal_spans()`: добавить weak-signal детектор для адресных обрывков — 6-значное число (потенциальный индекс) вне валидной группы, слово `обл.`/`город`/`ул.` без валидной сборки в текущем сегменте. Кандидаты только для мест, не покрытых `baseline_entities`.
5. Резолвинг цитаты идёт через существующий `_find_bounded()` — не менять.
6. `VerifierResult` уже возвращает Entity — но `EntityType` для address нужно замапить (у нас в реестре есть `ADDRESS`).
7. Побочный эффект: часть кейсов Задачи 4 (обрывки, которые сейчас не склеиваются, а после Задачи 4 будут отбрасываться) поднимется как «пропуск» и добавится обратно верификатором **уже цельным**, потому что окно ±160 символов вокруг обрывка захватит и улицу/дом.

**Verify.**
- `pytest backend/tests/masker/detect/test_verifier.py -x`
- Обновить `_ScriptedProvider` в тестах, чтобы он покрыл `type="address"`.
- Прогон `check_doc.py` с `MASKER_LLM=gigachat` на 2-3 фикстурах, сравнить количество address-спанов до/после.

## Задача 4. Адреса-обрывки (двухшаговый подход + расширение street-маркеров)

**Файлы.** `backend/src/masker/detect/address.py`, `backend/src/masker/detect/persons.py:_STREET_MARKERS`.

### 4.1 Расширенная склейка

- `_link_paragraph_split()` (address.py:423-454): расширить область поиска — вместо только соседнего абзаца искать «index+region-часть» и «street/building-часть» в окне ±300 символов (в пределах одного сегмента и в соседних сегментах той же ячейки таблицы).
- Ключ нормализации — уже есть, использовать его.

### 4.2 Отбраковка невалидных остатков

- После склейки: если результат **не проходит** `_is_sufficient()` (нет `index` и нет пары `settlement`+`street|building`), НЕ создавать address с `confidence=0.5|0.7`. Отбрасывать полностью. Это уберёт `'102400'`, `'обл., 184600'`, `'Мурманская обл., 184209'`.
- Единственное исключение — метка `«Адрес:»` (`value_labels` YAML) явно перед фразой; тогда оставить `confidence=0.5` как сейчас, потому что явная разметка сильнее эвристики.

### 4.3 Расширение `_STREET_MARKERS` полными формами

- `backend/src/masker/detect/persons.py:_STREET_MARKERS`: добавить `"улица"`, `"проспект"`, `"переулок"`, `"набережная"`, `"шоссе"`, `"бульвар"`, `"тупик"`, `"квартал"`, `"площадь"`, `"аллея"`, `"линия"`, `"проезд"`.
- Это чинит кейс `person 'Зои'` в «улица Зои Космодемьянской»: `preceded_by_address_marker()` начнёт возвращать `True` для полной формы.
- Проверить регистронезависимость (`.casefold()` уже применяется в `preceded_by_address_marker`).

### 4.4 `_NUMBER_VALUE_RE` НЕ трогать

Регэксп `\s*\.?\s*(\d[\w-]*)` затрагивает много тестов. Изменение — риск регрессии. Отбраковку делаем на уровне сборки адреса, а не парсинга чанков.

**Verify.**
- `pytest backend/tests/masker/detect/test_address.py -x` — все существующие тесты зелёные.
- Добавить тест: обрывок вида `'обл., 184600'` без соседней улицы → адрес не создан.
- Добавить тест: `'улица Зои Космодемьянской, 12'` → 1 address, 0 person.
- Прогон `.venv/bin/python scripts/check_doc.py fixtures/real-contracts/open-contracts/edukirovsk-2018-659372.pdf` — количество address снижается с 289 до ожидаемого, `'Зои'` в person исчезает.

## Postman-сценарии (одна коллекция, живая GigaChat)

**Файлы.**
- `backend/postman/triema-masker.postman_collection.json` (одна коллекция, папки внутри)
- `backend/postman/local.postman_environment.json`

**Environment vars.** `base_url=http://localhost:8000`, `token`, `run_id`, `object_name`, `compile_thread_id`.

**Пререквизит.** Бэкенд запущен с `MASKER_LLM=gigachat`. GigaChat токены прописаны в `.env`.

---

### Папка 1 — Задача 1: Схема отчёта (новые поля)

Шаги:

1. `POST {{base_url}}/auth/login` → сохранить `token` в env.
2. `POST {{base_url}}/uploads` multipart с `fixtures/labeled/contract_pdf_02_school.pdf` → `object_name`.
3. `POST {{base_url}}/runs` body `{"object_name":"{{object_name}}","types":["inn","passport","ogrn","address","person"]}` → `run_id`.
4. `GET {{base_url}}/runs/{{run_id}}` — polling (Tests: `if (pm.response.json().status !== "succeeded") { postman.setNextRequest(pm.info.requestName); }`).
5. `GET {{base_url}}/runs/{{run_id}}/report` — assertions:
   ```javascript
   const res = pm.response.json();
   pm.test("brief_summary присутствует", () => pm.expect(res.contract_summary).to.have.property("brief_summary"));
   pm.test("document_kind структурирован", () => {
     pm.expect(res.contract_summary.document_kind).to.include.keys("status","source");
   });
   pm.test("customer_fact.status валидный", () => {
     pm.expect(res.contract_summary.customer_fact.status)
       .to.be.oneOf(["found","ambiguous","not_found","confirmed"]);
   });
   pm.test("payment_facts массив", () => pm.expect(res.contract_summary.payment_facts).to.be.an("array"));
   pm.test("delivery_facts массив", () => pm.expect(res.contract_summary.delivery_facts).to.be.an("array"));
   pm.test("contract_amount_fact.currency", () =>
     pm.expect(res.contract_summary.contract_amount_fact).to.have.property("currency"));
   pm.test("telemetry присутствует", () => pm.expect(res).to.have.property("telemetry"));
   pm.test("llm.calls массив", () => pm.expect(res.telemetry.llm.calls).to.be.an("array"));
   ```

---

### Папка 2 — Задача 2 (И3): Пользовательские типы

Покрывает: compile → waiting (questions) → answers → done, preview, ошибки валидации.

**Шаг 2.1 — Негативные кейсы входного описания**

`POST {{base_url}}/custom_types/compile`

Запрос A — пустое описание:
```json
{"object_name":"{{object_name}}","descriptions":[""]}
```
Ожидание: `422`, тело содержит локализованное сообщение об ошибке.

Запрос B — описание 7 символов (ниже порога):
```json
{"object_name":"{{object_name}}","descriptions":["паспорт"]}
```
Ожидание: `422`.

Запрос C — только пробелы:
```json
{"object_name":"{{object_name}}","descriptions":["       "]}
```
Ожидание: `422`.

**Шаг 2.2 — Успешная компиляция (happy path, однозначное описание)**

`POST {{base_url}}/custom_types/compile`
```json
{
  "object_name": "{{object_name}}",
  "descriptions": ["инн поставщика — десятизначное число в реквизитах продавца"]
}
```

Tests:
```javascript
const res = pm.response.json();
pm.test("status 200", () => pm.response.to.have.status(200));
pm.test("есть thread_id", () => pm.expect(res).to.have.property("thread_id"));
pm.environment.set("compile_thread_id", res.thread_id);

// Если сразу done:
if (res.status === "done") {
  pm.test("compiled не пустой", () => pm.expect(res.compiled).to.be.an("array").with.length.above(0));
  pm.test("compiled[0].spec присутствует", () => pm.expect(res.compiled[0]).to.have.property("spec"));
  pm.test("FailedTypeOut.code если есть", () => {
    if (res.failed && res.failed.length > 0) {
      pm.expect(res.failed[0]).to.have.property("code");
    }
  });
}
// Если waiting (уточняющий вопрос):
if (res.status === "waiting") {
  pm.test("есть questions", () => pm.expect(res.questions).to.be.an("array").with.length.above(0));
}
```

**Шаг 2.3 — Ответ на уточняющий вопрос (если waiting)**

`POST {{base_url}}/custom_types/compile/{{compile_thread_id}}/answers`
```json
{"answers": {"0": "да, маскировать только ИНН в разделе реквизиты"}}
```

Tests:
```javascript
const res = pm.response.json();
pm.test("status 200", () => pm.response.to.have.status(200));
pm.test("compile завершилась", () => pm.expect(res.status).to.equal("done"));
pm.test("compiled не пуст", () => pm.expect(res.compiled).to.be.an("array").with.length.above(0));
pm.test("есть preview", () => {
  const c = res.compiled[0];
  if (c && c.preview) {
    pm.expect(c.preview).to.have.property("total_matches");
    pm.expect(c.preview.segments).to.be.an("array");
  }
});
```

**Шаг 2.4 — Намеренно невалидное описание (LLM cannot_compile)**

`POST {{base_url}}/custom_types/compile`
```json
{
  "object_name": "{{object_name}}",
  "descriptions": ["замаскируй всё что выглядит подозрительно или может быть секретным"]
}
```

Tests:
```javascript
const res = pm.response.json();
pm.test("status 200 или 422", () =>
  pm.expect([200, 422]).to.include(pm.response.code));
if (pm.response.code === 200 && res.failed && res.failed.length > 0) {
  pm.test("failed[0].code присутствует", () =>
    pm.expect(res.failed[0]).to.have.property("code"));
  pm.test("failed[0].reason на русском", () =>
    pm.expect(res.failed[0].reason).to.be.a("string").with.length.above(5));
}
```

**Шаг 2.5 — Preview для regex_llm_filter**

Этот шаг выполняется после того, как Шаг 2.2 вернул compile со спекой типа `regex_llm_filter`. Если компилятор вернул другой kind — шаг пропустить (тест помечается skip).

`POST {{base_url}}/custom_types/compile`
```json
{
  "object_name": "{{object_name}}",
  "descriptions": ["номера платёжных поручений — числа рядом со словами 'платёжное поручение' или 'п/п'"]
}
```

Tests:
```javascript
const res = pm.response.json();
if (res.status === "done" && res.compiled && res.compiled.length > 0) {
  const c = res.compiled[0];
  pm.test("preview не упал", () => pm.expect(c).to.have.property("preview"));
  if (c.preview) {
    pm.test("preview.total_matches число", () =>
      pm.expect(c.preview.total_matches).to.be.a("number"));
    pm.test("preview.segments массив", () =>
      pm.expect(c.preview.segments).to.be.an("array"));
  }
}
```

## Распараллеливание

Файловых пересечений между задачами почти нет:

| Задача | Основные файлы |
|--------|----------------|
| 1 | `api/schemas/report.py`, `scripts/dump_openapi.py`, `frontend/…/core.json` |
| 2 | `masker/customtypes/*`, `masker/typeconfig.py`, `api/schemas/custom_types.py`, `api/routers/custom_types.py`, `api/services/custom_types_service.py` |
| 3 | `masker/detect/verifier.py` |
| 4 | `masker/detect/address.py`, `masker/detect/persons.py` |

Все 4 задачи можно вести параллельными подветками. Единственная точка синхронизации — регенерация OpenAPI-снимка (`dump_openapi.py` → `yarn orval`). Каждая ветка **не коммитит** `frontend/…/core.json`; ведущий агент пересобирает снимок один раз при мерже.

Порядок финального шага (ведущий):
1. Слить все рабочие ветки в общую feature-интеграцию.
2. `cd backend && .venv/bin/python scripts/dump_openapi.py`.
3. `cd frontend && yarn orval`.
4. `make gate` (только ведущий).

Задачу 1 стоит закрыть первой (30 минут по оценке), чтобы фронт мог начать двигаться параллельно с остальными.

## Verify (сводно)

- `pytest backend/tests/api/test_runs_report.py backend/tests/masker/graph/test_report_node.py -x` (Задача 1)
- `pytest backend/tests/api/test_custom_types_schema.py backend/tests/api/test_custom_types_router.py backend/tests/masker/test_compiler.py backend/tests/masker/test_typeconfig.py backend/tests/masker/customtypes/test_preview.py -x` (Задача 2)
- `pytest backend/tests/masker/detect/test_verifier.py -x` (Задача 3)
- `pytest backend/tests/masker/detect/test_address.py -x` (Задача 4)
- `backend/.venv/bin/python scripts/check_doc.py fixtures/real-contracts/open-contracts/edukirovsk-2018-659372.pdf` — smoke на адреса.
- Postman-коллекция через живую GigaChat.
- Финальные ворота: `make gate` от корня (только ведущий, после мержа всех веток).

## Файл плана в репо

После утверждения перенести содержимое этого плана в `docs/plans/2026-09-11-frontend-unblock-i3-r7-address.md` (первым коммитом на feature-ветке, отдельно от кода).
