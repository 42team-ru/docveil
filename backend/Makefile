# bin/python — POSIX-раскладка venv (по умолчанию, см. AGENTS.md); Scripts/python.exe — Windows.
# `=` вместо `:=`: подставляется заново на каждой строке рецепта, уже после того как install создаст venv.
PY = $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

# Подтягиваем .env (DATABASE_URL, JWT_SECRET, MINIO_*) в окружение рецептов make.
# Сначала свой backend/.env, иначе — общий ../.env из корня репозитория.
ENV_FILE := $(firstword $(wildcard .env ../.env))
ifneq (,$(ENV_FILE))
include $(ENV_FILE)
export
endif

.PHONY: gate tasks test eval bench bench-matrix demo fmt install gate-selftest migrate migration api seed-admin

install:
	uv venv --python 3.14 .venv
	uv pip install --python $(PY) -e ".[dev]"

gate:
	./scripts/gate.sh

# Прогресс по TASKS.md. Источник истины — сам TASKS.md,
# второго списка задач не заводим: он разъедется с первым.
tasks:
	@$(PY) scripts/tasks_progress.py

# PYTEST_WORKERS=0 — последовательный прогон (отладка), по умолчанию 4 процесса.
PYTEST_WORKERS ?= 4

test:
	$(PY) -m pytest -q -n $(PYTEST_WORKERS)

eval:
	$(PY) -m masker.eval

# К3 — замеры практического эффекта: таблица ЗАМЕРЕНО/ПРОГНОЗ (docs/SCORING.md §2).
# Прогон реального конвейера на fixtures/labeled+holdout, десятки секунд из-за
# 46-страничного PDF в корпусе — это ожидаемо, не зависание.
bench:
	$(PY) -m masker.bench

# К4 — матричный бенчмарк слоёв детекции (rules/ner/gliner) и провайдеров LLM
# (none/cassette/gigachat/openrouter). НЕ ЧАСТЬ `make gate`, не запускается
# по умолчанию нигде: `gigachat`/`openrouter` тратят деньги и требуют сети.
# Без GIGACHAT_CREDENTIALS/OPENROUTER_API_KEY живые клетки помечаются
# пропущенными, а не падают — это единственная сетевая цель в этом Makefile.
bench-matrix:
	$(PY) -m masker.bench_matrix

demo:
	$(PY) -m masker.cli fixtures/labeled/*.docx --out out/ --types all

fmt:
	$(PY) -m ruff format src tests && $(PY) -m ruff check --fix src tests

# Ворота, которые всегда зелёные, хуже отсутствия ворот.
# Ломаем инвариант нарочно и убеждаемся, что ворота это ловят.
gate-selftest:
	@$(PY) -m pytest -q tests/masker/test_gate_selftest.py

# Инфраструктура (docker compose up/down/logs/db-shell) переехала в корневой
# Makefile — там же лежит docker-compose.yml.

migrate:
	$(PY) -m alembic upgrade head

migration:
	$(PY) -m alembic revision --autogenerate -m "$(m)"

# Дефолт порта — на уровне make ($(if ...)), не шелла ($${VAR:-default}):
# последнее раскрывает только POSIX sh, а на Windows без sh.exe на PATH make
# рецепты гонит через cmd.exe, который такой синтаксис не понимает и передаёт
# uvicorn буквальную строку «${APP_PORT:-8000}» как порт.
api:
	$(PY) -m uvicorn api.main:app --reload --app-dir src --host 0.0.0.0 --port $(if $(APP_PORT),$(APP_PORT),8000)

# make seed-admin email=admin@x.com password=secret full_name="Admin"
# make seed-admin email=admin@x.com password=new-secret reset_password=1
# либо задать ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_FULL_NAME в .env и звать без аргументов.
seed-admin:
	$(PY) scripts/seed_admin.py $(if $(email),--email "$(email)") $(if $(password),--password "$(password)") $(if $(full_name),--full-name "$(full_name)") $(if $(reset_password),--reset-password)
