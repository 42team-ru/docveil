# bin/python — POSIX-раскладка venv (по умолчанию, см. AGENTS.md); Scripts/python.exe — Windows.
# `=` вместо `:=`: подставляется заново на каждой строке рецепта, уже после того как install создаст venv.
PY = $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)

# Подтягиваем .env (DATABASE_URL, JWT_SECRET, MINIO_*) в окружение рецептов make.
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: gate test eval demo fmt install gate-selftest up down logs migrate migration db-shell api seed-admin

install:
	uv venv --python 3.14 .venv
	uv pip install --python $(PY) -e ".[dev]"

gate:
	./scripts/gate.sh

test:
	$(PY) -m pytest -q

eval:
	$(PY) -m masker.eval

demo:
	$(PY) -m masker.cli fixtures/labeled/*.docx --out out/ --types all

fmt:
	$(PY) -m ruff format src tests && $(PY) -m ruff check --fix src tests

# Ворота, которые всегда зелёные, хуже отсутствия ворот.
# Ломаем инвариант нарочно и убеждаемся, что ворота это ловят.
gate-selftest:
	@$(PY) -m pytest -q tests/test_gate_selftest.py

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

migrate:
	$(PY) -m alembic upgrade head

migration:
	$(PY) -m alembic revision --autogenerate -m "$(m)"

db-shell:
	docker compose exec postgres psql -U $${POSTGRES_USER:-masker} -d $${POSTGRES_DB:-masker}

api:
	$(PY) -m uvicorn api.main:app --reload --app-dir src --host 0.0.0.0 --port 8000

# make seed-admin email=admin@x.com password=secret full_name="Admin"
# либо задать ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_FULL_NAME в .env и звать без аргументов.
seed-admin:
	$(PY) scripts/seed_admin.py $(if $(email),--email "$(email)") $(if $(password),--password "$(password)") $(if $(full_name),--full-name "$(full_name)")
