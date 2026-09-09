# Установка и запуск

Практическая инструкция: что поставить, как запустить обезличивание одного
файла, какие переменные окружения на что влияют и что делать, если
установка не идёт гладко. Про сам продукт — `../README.md`, про устройство
пайплайна — `../ARCHITECTURE.md`, про флаги CLI и формат отчёта —
`CLI.md`.

Весь Python-код и все команды ниже — из каталога `backend/`, если явно не
сказано иное.

## Что нужно поставить

| Что | Версия | Зачем | Обязательно? |
|---|---|---|---|
| Python | 3.13+ (в разработке используется 3.14) | сам проект | да |
| [`uv`](https://docs.astral.sh/uv/) | любая современная | venv и установка зависимостей | да |
| `tesseract-ocr` + языковой пакет `rus` | системный пакет | OCR-провайдер `tesseract` для сканов (опционально) | нет, только для `MASKER_OCR=tesseract` |

Проверить, что `uv` и `tesseract` видны:

```bash
uv --version
tesseract --version   # нужен пакет tesseract-ocr-rus, иначе распознавание пойдёт без русского
```

На Debian/Ubuntu Tesseract с русским языком ставится так:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-rus
```

Если `tesseract` не установлен — это не блокер. По умолчанию (`MASKER_OCR`
не задан) обезличивание сканов использует `FakeOCR` в тестах/CI и требует
реальный движок (`paddle`/`rapid`/`tesseract`) только при явном запросе на
сканах, см. «OCR» ниже.

## Установка проекта

```bash
git clone <repo> triema-masker
cd triema-masker/backend
make install     # uv venv --python 3.14 .venv && uv pip install -e ".[dev]"
```

`make install` создаёт `.venv` в `backend/` и ставит основные зависимости
плюс dev-инструменты (`pytest`, `ruff`, `mypy`). Дальше весь Python — только
из этого venv: `backend/.venv/bin/python`, никогда системный `python3`.

Проверить, что установка прошла:

```bash
.venv/bin/masker --help
```

### Опциональные зависимости (extras)

Основные зависимости достаточны для DOCX/PDF/XLSX без OCR и без GLiNER.
Два extra ставятся отдельно, когда они нужны:

```bash
# Реальный OCR для сканов (PaddleOCR + RapidOCR); без этого extra доступен
# только MASKER_OCR=fake (тесты/CI) и MASKER_OCR=tesseract (нужен только
# системный tesseract, extra не требуется).
uv pip install --python .venv/bin/python -e ".[ocr]"

# GLiNER2 — опциональный локальный детектор для пользовательских типов
# сущностей; тянет torch. Модель кэшируется отдельно, см. ниже.
uv pip install --python .venv/bin/python -e ".[gliner]"
```

Пакеты ставить только через `uv pip install --python .venv/bin/python <pkg>`
и сразу дописывать в `pyproject.toml` — так делает весь проект, включая
агентов-разработчиков (`AGENTS.md`).

### Первый запуск качает модели — это нормально

- **Natasha** (русский NER, слой 2 детекции) распакует эмбеддинги при первом
  импорте; в `.venv` они уже входят зависимостью, отдельно скачивать не
  нужно.
- **PaddleOCR** (`MASKER_OCR=paddle`) при первом вызове `recognize()` тянет
  веса в `~/.paddleocr/` — не в репозиторий. Нужна сеть один раз, дальше
  работает офлайн.
- **GLiNER2** (опционально, для расширения на свои типы через локальную
  модель) читает веса из `models/gliner`, путь переопределяется
  `MASKER_GLINER_PATH`; если каталога нет — `scripts/warm_gliner.py`
  скажет, что запустить.

## Быстрая проверка на одном файле

```bash
cd backend
.venv/bin/masker fixtures/labeled/contract_01.docx \
  --out out/check \
  --types all \
  --redact-style both \
  --html
```

Флаг `--redact-style` обязателен, если нужны сами обезличенные файлы:
**без него CLI создаёт только `preview.docx` (с исходным текстом, только
для проверки детектора) и `report.json`, но не создаёт `masked_black.*` /
`masked_highlight.*`.** Это касается и `make demo` — он тоже не передаёт
`--redact-style`, поэтому в `out/` после него будут только превью и отчёты.

После запуска в `out/check/contract_01/` появятся:

| Файл | Что это |
|---|---|
| `masked_black.docx` | версия для передачи наружу — чёрная заливка, маркер белым |
| `masked_highlight.docx` | версия для своей проверки — жёлтая подсветка, маркер виден |
| `preview.docx` | **содержит исходный текст**, только для отладки детектора, наружу не отдавать |
| `report.json` | сводка находок, сертификат обезличивания, карточка договора, все решения |
| `report.html` | тот же отчёт человекочитаемо (только при `--html`) |

Файлы создаются с правами `0600`. Полный разбор флагов и содержимого
`report.json` — `CLI.md`.

## Переменные окружения

| Переменная | Значения | Дефолт | Влияет на |
|---|---|---|---|
| `MASKER_LLM` | `fake` \| `cassette` \| `openrouter` \| `gigachat` | `fake` | какой `LLMProvider` использовать для ролей сторон, судьи, своих типов и карточки договора |
| `MASKER_LLM_MODEL` | название модели | — | модель у выбранного провайдера (обязательно для `openrouter`/`gigachat`, если не задано в `--llm-config`) |
| `OPENROUTER_API_KEY` | ключ | — | авторизация `OpenRouterProvider` |
| `GIGACHAT_CREDENTIALS` | ключ/токен | — | авторизация `GigaChatProvider` |
| `MASKER_LLM_GIGACHAT_SCOPE` | scope GigaChat API | `GIGACHAT_API_PERS` (см. `gigachat.py`) | область токена GigaChat |
| `MASKER_LLM_GIGACHAT_CA_BUNDLE` | путь к файлу `.pem`/`.cer` | не задана (системное хранилище) | доверенный корневой сертификат для TLS к GigaChat (например, сертификат Минцифры России), если он уже есть на машине; проект его не скачивает и не хранит |
| `MASKER_LLM_GIGACHAT_INSECURE_SKIP_TLS_VERIFY` | `1`/`true`/`yes` | не задана (проверка TLS всегда включена) | полностью отключить проверку TLS-сертификата GigaChat — небезопасно, только осознанным включением; предпочтительно вместо этого задать `MASKER_LLM_GIGACHAT_CA_BUNDLE` |
| `MASKER_LLM_CASSETTE_DIR` | путь к каталогу | `fixtures/llm/roles` | откуда `CassetteProvider` читает записанные ответы |
| `MASKER_OCR` | `fake` \| `paddle` \| `paddle_vl` \| `rapid` \| `tesseract` | `fake` | какой OCR-провайдер обрабатывает сканированные PDF |
| `MASKER_GLINER_PATH` | путь к каталогу | `models/gliner` | откуда GLiNER2 читает веса (опционально, только с extra `gliner`) |
| `PADDLE_NO_ORI_CLASSIFY` | `1`/`true`/`yes` | не задана | отключить автоопределение ориентации страницы в PaddleOCR |
| `PYTEST_WORKERS` | целое число | `0` (последовательно в `gate.sh`) | параллелизм pytest в `make test`/`make gate` |

Ни одна из них не обязательна для базового сценария «обезличить DOCX/PDF/XLSX
без сети»: без всех переменных `MASKER_LLM=fake` и `MASKER_OCR=fake`
работают по умолчанию, и весь пайплайн, кроме живого вызова модели,
доступен офлайн.

### Живой LLM для ролей сторон, своих типов и карточки договора

Без ключа профилирование (`--profile`) работает на эвристике и
`FakeProvider`/`CassetteProvider` — роли сторон определяются по преамбуле
и подписям, без сети. Чтобы подключить настоящую модель:

```bash
cd backend
export OPENROUTER_API_KEY='...'          # или GIGACHAT_CREDENTIALS для GigaChat
MASKER_LLM=openrouter MASKER_LLM_MODEL='z-ai/glm-5.3-flash' \
  .venv/bin/masker fixtures/labeled/contract_08_roles.docx \
  --out out/openrouter-check \
  --profile \
  --allow-remote-pii
```

Либо через YAML-конфиг (`masker.llm.yaml` в `backend/` — шаблон без
секрета, ключ передаётся окружением):

```bash
.venv/bin/masker fixtures/labeled/contract_08_roles.docx \
  --out out/openrouter-check \
  --profile \
  --llm-config masker.llm.yaml \
  --allow-remote-pii
```

**`--allow-remote-pii` обязателен**, если провайдер не локальный: команда
отправляет во внешний API найденные исходные PII и контекстные фрагменты
документа, и это осознанное решение, а не поведение по умолчанию.

`report.json` получит секцию `profile_judge` — профили, роль, число вызовов
модели, диагностика, вердикты и вопросы. Живой сквозной прогон через
настоящий GigaChat — тест `@pytest.mark.e2e` (`pytest -m e2e`), не часть
обычного `make gate`.

**Честно про GigaChat сейчас:** провайдер и strict-схема готовы и покрыты
тестами, но кассеты с ответами (`fixtures/llm/roles`) записаны нейтральными
заглушками — ключей GigaChat в среде разработки нет. Прирост метрик от
модели не измерен; чтобы его измерить, кассеты нужно перезаписать с живым
GigaChat при наличии ключа.

### OCR для сканированных PDF

```bash
uv pip install --python .venv/bin/python -e ".[ocr]"   # один раз, если нужен paddle/rapid
MASKER_OCR=paddle .venv/bin/masker scan.pdf --out out/scan-check --types all --redact-style both
```

`MASKER_OCR=tesseract` не требует extra `ocr` — только системный пакет
`tesseract-ocr-rus` (см. выше). Неизвестное значение `MASKER_OCR` — это явная
ошибка (`OCRError` со списком доступных имён), а не тихий откат на `fake`.

## Команды

Все — из `backend/` (или из корня репозитория, кроме `make bench`, см.
«Известные шероховатости» ниже):

```bash
make gate      # единственные ворота: линт + типы + тесты + предметные метрики
make test      # только pytest (PYTEST_WORKERS=N — параллельно, по умолчанию 0)
make eval      # precision/recall/robust_recall/holdout/certificate по корпусу fixtures/
make bench     # таблица ЗАМЕРЕНО: время по стадиям, память, recall — из backend/
make demo      # прогон на fixtures/labeled/*.docx, результат в out/ (без --redact-style)
make fmt       # ruff format + ruff check --fix
```

`make eval` и `make bench` гоняют настоящий графовый конвейер по всему
корпусу `fixtures/` — это не долю секунды, а десятки секунд (в `fixtures/`
есть PDF на 46 страниц). Это ожидаемо, не зависание.

Веб-часть (FastAPI + Postgres + MinIO, пока без готового фронтенда) —
из корня репозитория. Шаблон переменных — `backend/.env.example`; куда его
скопировать, зависит от того, что запускаете: `docker compose` в
`docker-compose.yml` подставляет переменные из `.env` **в корне**
репозитория (или из уже экспортированного окружения), а `backend/Makefile`
(`make api`, `make migrate`, `make seed-admin`) ищет сначала `backend/.env`,
и только если его нет — `../.env`:

```bash
cp backend/.env.example .env   # для `make up` (docker compose читает .env из корня)
make up                        # docker compose: postgres + minio + backend
make api                       # локальный uvicorn без контейнера (нужен DATABASE_URL — тот же .env)
make down                      # остановить контейнеры
```

## Если что-то не ставится

- **`ModuleNotFoundError: pkg_resources` при импорте Natasha.** Транзитивная
  зависимость `pymorphy2` использует `pkg_resources`, которого нет в
  `setuptools>=81`. В `pyproject.toml` уже стоит пин `setuptools<81` — если
  ошибка всё равно всплыла, значит venv собран не через `make install`
  (например, вручную `pip install natasha` в чужое окружение) и пина нет;
  пересоздайте venv через `make install`.
- **`paddleocr`/`rapidocr-onnxruntime` не устанавливается или падает на
  импорте.** Это extra `ocr`, не входит в базовую установку. Без него
  доступны `MASKER_OCR=fake` (тесты) и `MASKER_OCR=tesseract` (нужен только
  системный Tesseract, см. выше) — обезличивание текстовых DOCX/PDF/XLSX
  это не блокирует. Ставить `torch`/`paddlepaddle` на слабой машине без GPU
  не обязательно ради основного сценария.
- **`uv lock --check` падает в `make gate`.** `pyproject.toml` и `uv.lock`
  разошлись — кто-то поправил зависимости руками. Пересоздать лок:
  `uv lock` из `backend/`, закоммитить оба файла вместе.
- **`--profile`/`--llm-config` падает с `LLMError: не задана переменная
  окружения ...`.** Провайдер выбран (`openrouter`/`gigachat`), но ключ не
  экспортирован в текущий шелл. Проверить `echo $OPENROUTER_API_KEY` (или
  `$GIGACHAT_CREDENTIALS`) перед запуском; без ключа используйте
  `MASKER_LLM=fake` или `cassette`.
- **CLI создал только `preview.docx`, обезличенных файлов нет.** Не был
  передан `--redact-style marker|blackbox|both` — см. «Быстрая проверка»
  выше.
- **GigaChat падает с `SSL: CERTIFICATE_VERIFY_FAILED: self-signed
  certificate in certificate chain`.** GigaChat работает через сертификаты
  Минцифры России, которых обычно нет в стандартном системном хранилище
  доверенных корневых сертификатов. Если такой сертификат у вас уже есть —
  укажите путь к нему в `MASKER_LLM_GIGACHAT_CA_BUNDLE`. Полное отключение
  проверки TLS (`MASKER_LLM_GIGACHAT_INSECURE_SKIP_TLS_VERIFY=1`) технически
  возможно, но небезопасно и не включено по умолчанию — используйте только
  осознанно.
- **`make gate` красный на метрике, а не на тесте.** Это ворота работают
  как задумано: порог в `masker/eval.py` подобран по фактическому замеру
  (см. «Правило порогов», `TASKS.md`), и его нельзя тихо понизить, чтобы
  ворота позеленели — надо чинить причину регрессии.

## Известные шероховатости

- **`make bench` не проксируется корневым `Makefile`.** Список
  `BACKEND_TARGETS` в корневом `Makefile` не включает `bench` — команда
  работает только запущенная из `backend/` (`cd backend && make bench`).
  Остальные питон-цели (`gate`, `test`, `eval`, `demo`, …) вызываются и из
  корня, и из `backend/` одинаково.
- **`make demo` берёт только `*.docx`.** Цель в `backend/Makefile` собирает
  `fixtures/labeled/*.docx` — PDF и XLSX из того же корпуса демо не
  затрагивает. Для остальных форматов вызывайте `masker` напрямую на нужном
  файле, как в разделе «Быстрая проверка».
