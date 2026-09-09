# Хендофф: O1 — контракты и абстракция OCR-провайдера (09.09.2026)

Первая из пяти подзадач плана `docs/plans/T2.3-ocr-paddleocr.md` (OCR для
скан-PDF на базе PaddleOCR). Изолированный слой без внешних движков —
дальнейшие подзадачи O2–O5 опираются ровно на эти контракты.

**Ветка:** `feat/ocr-provider-abstraction` (создана до первой правки, master
не тронут).

**Состояние: ворота зелёные, все существующие тесты + новые 10 — passed.**

---

## 1. Что закрыто по приёмке O1

Из плана:

| Пункт приёмки | Статус |
|---|---|
| `make gate` = 0 с `MASKER_OCR=fake` по умолчанию | ✅ (см. §4) |
| Тест изоляции слоя (`test_no_ocr_imports_outside_layer`) | ✅ |
| Тест дефолта/env/unknown/paddle-без-extra в `test_select.py` | ✅ |
| Тест `FakeOCR` (`test_fake.py`) | ✅ |
| `pip install -e .` не тянет `paddleocr`; `pip install -e .[ocr]` тянет | ✅ (`pyproject.toml`) |

Итог тестов: `1848 passed, 2 skipped`, из них новых — 10 в
`tests/masker/ocr/`.

---

## 2. Что появилось в коде

**Новый слой `masker.ocr`** (симметрично `masker.llm`):

- `src/masker/ocr/__init__.py` — публичный API слоя (`OCRProvider`,
  `OCRLine`, `OCRError`, `select_ocr`).
- `src/masker/ocr/provider.py` — контракты. `OCRProvider` — Protocol с
  `runtime_checkable`; `OCRLine` — dataclass `text/bbox/polygon/confidence/
  order/extra`. Координаты — **пиксельные координаты исходного
  изображения**, пересчёт в pt страницы — задача ingest'а (O3).
- `src/masker/ocr/fake.py` — детерминированный `FakeOCR`. Поддерживает
  глобальные строки и переопределение по ключу `(width, height)` — этого
  хватит для смешанных фикстур в O3/O5 без файлового чтения. Проверяет
  форму входного изображения: `(H, W, 3)` uint8. `.calls` для тестов.
- `src/masker/ocr/select.py` — `select_ocr(name=None)`. Порядок: аргумент
  → `MASKER_OCR` → дефолт `fake`. Неизвестное имя → `OCRError` со списком
  доступных. `paddle`/`tesseract` — ленивый импорт из `masker.ocr.paddle`
  и `masker.ocr.tesseract` (появятся в O2 и опционально позже); если extra
  не установлена — `OCRError` c текстом `pip install triema-masker[ocr]`,
  а не голый `ModuleNotFoundError`.

**Правки контрактов:**

- `src/masker/model.py::Segment` — добавлено поле `origin: str = "text"`.
  Значение по умолчанию сохраняет все 93 существующих вызова `Segment(...)`.
  Для OCR-сегментов O3 будет ставить `origin="ocr"`; детекция/политика/план
  этого поля не читают — им прозрачно, откуда пришёл текст.
- `src/masker/graph/nodes.py::extract_node` — `origin` попадает в JSON-
  сериализацию сегмента, `_document` десериализует с дефолтом `"text"`
  (обратно совместимо со старыми чекпойнтами).

**Инфраструктура:**

- `backend/pyproject.toml` — extra `ocr = ["paddleocr>=3.0"]` и pytest-
  маркер `ocr`. Основные зависимости не тронуты; `pytesseract` уже был
  здесь как основная зависимость и остаётся.
- `backend/masker.ocr.yaml` — конфиг-заглушка по аналогии с
  `masker.llm.yaml` (дефолт `fake`, `dpi: 300`, комментарии про
  `use_doc_orientation_classify`). Читать этот файл будем в O2, сейчас он
  документация.

**Тесты:**

- `tests/masker/ocr/test_layer_boundary.py` — AST-grep, `paddleocr`/
  `pytesseract` не импортируются нигде вне `src/masker/ocr/` (клон
  `test_no_llm_imports_outside_layer`).
- `tests/masker/ocr/test_select.py` — дефолт, чтение env, приоритет
  явного аргумента, unknown-name c перечнем доступных, «paddle без extra»
  → `OCRError` c маркером `triema-masker[ocr]`.
- `tests/masker/ocr/test_fake.py` — глобальные строки и счётчик,
  пустой результат, размер-специфичные строки, отказ на грейскейл-массиве.

---

## 3. Что сознательно НЕ делали в O1

- **`FakeOCR` не читает `*.ocr.json` рядом с картинкой.** В плане это
  упоминалось, но фикстурного корпуса ещё нет (появится в O5), а
  конструктор с явными строками покрывает и юниты, и грядущие интеграции.
  Файловая подгрузка — фабрика фикстур, а не провайдер.
- **Модуль `masker.ocr.paddle` не создан.** Селектор ссылается на него
  через ленивый импорт: `OCRError` вместо `ModuleNotFoundError` — уже
  часть контракта. Реальный класс — O2.
- **`RunDeps` не расширён полем `ocr`.** Разбор скан-страниц ещё нигде
  не вызывается — расширять зависимости узлов раньше их использования
  бессмысленно. Правка `RunDeps` — начало O3.

---

## 4. Проверка

Окружение потребовало `uv sync --extra dev` (после коммита 8dc2bce
`setuptools<81` не был установлен в `.venv`) — baseline тоже падал на
`pkg_resources` до синка, регрессии от O1 нет.

Прогон:

```
cd backend
./scripts/gate.sh
```

Ожидаемо: линт/формат/типы/lock зелёные, `1848 passed, 2 skipped`,
метрики `masker.eval --gate` без порогов ниже фактических.

---

## 5. Что дальше — O2

Основной класс `PaddleOCRProvider` (PP-OCR v3.x, актуальный API через
`from paddleocr import PaddleOCR` c параметрами
`use_doc_orientation_classify=True`, `use_textline_orientation=True`,
`use_doc_unwarping=False`; язык — сначала `ru`, фолбэк `cyrillic`).
Ленивая инициализация модели на первый вызов `recognize`; веса кэшируются
в `~/.paddleocr/`. `pytest.mark.models` smoke-тест на подготовленном PNG
c русским текстом «Иванов ИНН 7707083893». Слот `PaddleVLProvider` —
скелет без реализации.
