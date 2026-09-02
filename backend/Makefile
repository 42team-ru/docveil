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

.PHONY: gate test eval demo fmt install gate-selftest migrate migration api seed-admin

install:
	uv venv --python 3.14 .venv
	uv pip install --python $(PY) -e ".[dev]"

gate:
	./scripts/gate.sh

# PYTEST_WORKERS=0 — последовательный прогон (отладка), по умолчанию 4 процесса.
PYTEST_WORKERS ?= 4

test:
	$(PY) -m pytest -q -n $(PYTEST_WORKERS)

eval:
	$(PY) -m masker.eval

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

api:
	$(PY) -m uvicorn api.main:app --reload --app-dir src --host 0.0.0.0 --port 8000

# make seed-admin email=admin@x.com password=secret full_name="Admin"
# либо задать ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_FULL_NAME в .env и звать без аргументов.
seed-admin:
	$(PY) scripts/seed_admin.py $(if $(email),--email "$(email)") $(if $(password),--password "$(password)") $(if $(full_name),--full-name "$(full_name)")
