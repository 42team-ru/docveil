PY := .venv/bin/python

.PHONY: gate test eval demo fmt install gate-selftest

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
