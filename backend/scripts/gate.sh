#!/usr/bin/env bash
# Единственные ворота проекта. Ненулевой код возврата = работа не принята.
# Ворота обязаны уметь не пройти: проверить это можно `make gate-selftest`.
set -uo pipefail

# bin/python — POSIX-раскладка venv (по умолчанию, см. AGENTS.md);
# Scripts/python.exe — Windows. Та же развилка, что в Makefile: без неё ворота
# на Windows падают всеми шагами сразу «No such file or directory».
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
export PYTHONPATH=src
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
FAILED=()

# Тесты гоняются последовательно. Замер 09.09.2026 на 1943 тестах
# (`./scripts/bench-tests.sh`, 32 ядра): последовательно 49.7 с, 4 воркера
# 60 с, 8 воркеров 274 с, 12 — 227 с, 16 — 246 с. Параллелизм здесь не
# окупается и мешает: часть тестов сама поднимает вложенные процессы
# (`test_gate_selftest`, `test_bench`), и воркеры дерутся с ними за ядра.
#
# Прежнее значение 4 стояло по замеру той эпохи, когда весь прогон занимал
# ~13 секунд и цена импорта Natasha в каждом воркере доминировала. После
# того как пять самых долгих тестов ускорены со 162 с до ~11 с, это
# обоснование перестало действовать.
#
# PYTEST_WORKERS=N включает параллельный запуск обратно, если понадобится.
# Перед сменой значения — перемерить `./scripts/bench-tests.sh`, а не
# ставить число на глаз.
WORKERS="${PYTEST_WORKERS:-0}"

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
step "тесты"    $PY -m pytest -q -n "$WORKERS" -m "not gliner and not e2e"
step "метрики"  $PY -m masker.eval --gate

echo
# Прогресс печатается при любом исходе: и когда ворота зелёные (видно,
# сколько осталось), и когда красные (видно, на каком фоне это падение).
# Своим кодом возврата ворота не рушит — это справка, а не проверка.
$PY scripts/tasks_progress.py || true

if [ ${#FAILED[@]} -eq 0 ]; then
    echo "ВОРОТА ПРОЙДЕНЫ"
    exit 0
fi
echo "ВОРОТА НЕ ПРОЙДЕНЫ (${#FAILED[@]}): ${FAILED[*]}"
exit 1
