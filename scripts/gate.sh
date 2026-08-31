#!/usr/bin/env bash
# Единственные ворота проекта. Ненулевой код возврата = работа не принята.
# Ворота обязаны уметь не пройти: проверить это можно `make gate-selftest`.
set -uo pipefail

PY=.venv/bin/python
export PYTHONPATH=src
FAILED=()

# Тесты гоняются в несколько процессов (pytest-xdist). Замерено на этом
# репозитории: 4 воркера дают ~13.1 с против ~15.4 с последовательно,
# 8 и больше — уже медленнее, потому что упираемся не в счёт, а в импорт
# модулей и сборку теггера Natasha в каждом воркере. PYTEST_WORKERS=0
# отключает параллельный запуск (нужно, когда ловишь падение отладчиком).
WORKERS="${PYTEST_WORKERS:-4}"

step() {
    local name="$1"; shift
    echo "───── $name"
    if "$@"; then
        echo "  ok"
    else
        echo "  ПРОВАЛ: $name"
        FAILED+=("$name")
    fi
}

step "линт"     $PY -m ruff check src tests
step "формат"   $PY -m ruff format --check src tests
step "типы"     $PY -m mypy src
step "лок"      uv lock --check
step "тесты"    $PY -m pytest -q -n "$WORKERS"
step "метрики"  $PY -m masker.eval --gate

echo
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "ВОРОТА ПРОЙДЕНЫ"
    exit 0
fi
echo "ВОРОТА НЕ ПРОЙДЕНЫ (${#FAILED[@]}): ${FAILED[*]}"
exit 1
