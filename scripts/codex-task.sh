#!/usr/bin/env bash
# Неблокирующий запуск задач в Codex.
#
# Зачем отдельно от `codex.sh exec`. Прямой `exec` держит вызывающего до
# конца работы и всё это время молчит: Codex пишет stdout одним куском в
# самом конце. Задача на полчаса означает полчаса тишины, а вызывающий с
# таймаутом (агент, CI, хук) просто отваливается и теряет результат, хотя
# Codex продолжает работать. Плюс промпт приходилось втискивать в аргумент
# командной строки, где кавычки и обратные слэши живут своей жизнью.
#
# Здесь промпт читается из файла или stdin, прогон уходит в фон, события
# пишутся построчно (`--json`), последнее сообщение — отдельным файлом
# (`-o`). Вызывающий получает управление сразу и потом спрашивает статус.
#
#   ./scripts/codex-task.sh start роли -f prompt.md
#   cat prompt.md | ./scripts/codex-task.sh start роли
#   ./scripts/codex-task.sh status роли
#   ./scripts/codex-task.sh result роли
#   ./scripts/codex-task.sh watch роли        # живая лента
#   ./scripts/codex-task.sh resume роли -f followup.md
#   ./scripts/codex-task.sh list
#
# Артефакты прогона лежат в `.codex/runs/<имя>/` (каталог в .gitignore):
#   prompt.md      что просили
#   events.jsonl   поток событий, пополняется во время работы
#   last.md        последнее сообщение агента
#   session        id сессии Codex (для `codex exec resume`)
#   exit           код возврата, появляется только после завершения
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS="$ROOT/.codex/runs"

die() { echo "codex-task: $*" >&2; exit 1; }

usage() {
    sed -n '2,29p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

run_dir() {
    local name="$1"
    [ -n "$name" ] || die "не задано имя задачи"
    printf '%s/%s' "$RUNS" "$name"
}

# Имя последней запущенной задачи — чтобы `status` без аргументов отвечал
# про то, что человек только что запустил.
latest_name() {
    [ -d "$RUNS" ] || return 1
    local newest
    newest="$(ls -1dt "$RUNS"/*/ 2>/dev/null | head -1)" || return 1
    [ -n "$newest" ] || return 1
    basename "$newest"
}

read_prompt() {
    local file="$1"
    if [ -n "$file" ]; then
        [ -f "$file" ] || die "нет файла с промптом: $file"
        cat "$file"
    else
        # Без stdin ждать нечего: молча зависнуть здесь — ровно та беда,
        # ради которой скрипт и написан.
        [ ! -t 0 ] || die "промпт не задан: укажите -f ФАЙЛ или подайте текст на stdin"
        cat
    fi
}

cmd_start() {
    local name="" file="" resume_id="" passthrough=()
    while [ $# -gt 0 ]; do
        case "$1" in
            -f|--file) file="${2:-}"; shift 2 ;;
            --resume) resume_id="${2:-}"; shift 2 ;;
            -h|--help) usage ;;
            --) shift; passthrough+=("$@"); break ;;
            -*) passthrough+=("$1"); shift ;;
            *) if [ -z "$name" ]; then name="$1"; else passthrough+=("$1"); fi; shift ;;
        esac
    done
    [ -n "$name" ] || die "не задано имя задачи: codex-task.sh start ИМЯ -f ФАЙЛ"

    local dir; dir="$(run_dir "$name")"
    if [ -d "$dir" ] && [ ! -f "$dir/exit" ] && [ -f "$dir/pid" ] \
       && kill -0 "$(cat "$dir/pid")" 2>/dev/null; then
        die "задача «$name» уже выполняется (pid $(cat "$dir/pid")); см. status"
    fi
    mkdir -p "$dir"
    read_prompt "$file" > "$dir/prompt.md"
    [ -s "$dir/prompt.md" ] || die "промпт пустой"
    rm -f "$dir/exit" "$dir/session" "$dir/events.jsonl" "$dir/last.md"
    date +%s > "$dir/started"

    local -a argv=(exec --json -o "$dir/last.md")
    [ -n "$resume_id" ] && argv=(exec resume "$resume_id" --json -o "$dir/last.md")
    argv+=("${passthrough[@]}" -)

    # setsid, чтобы прогон пережил закрытие терминала вызывающего: смысл
    # обёртки в том, что задача идёт своим ходом, а не умирает вместе с
    # тем, кто её запустил.
    setsid nohup bash -c '
        "$1"/scripts/codex.sh "${@:3}" < "$2/prompt.md" >> "$2/events.jsonl" 2>&1
        echo $? > "$2/exit"
    ' _ "$ROOT" "$dir" "${argv[@]}" >/dev/null 2>&1 &
    echo $! > "$dir/pid"

    echo "запущено: $name (pid $(cat "$dir/pid"))"
    echo "  события:   $dir/events.jsonl"
    echo "  результат: $dir/last.md"
    echo "  статус:    ./scripts/codex-task.sh status $name"
}

cmd_resume() {
    local name="${1:-}"; shift || true
    [ -n "$name" ] || die "не задано имя задачи"
    local dir; dir="$(run_dir "$name")"
    local session; session="$(cat "$dir/session" 2>/dev/null || true)"
    [ -n "$session" ] || die "у задачи «$name» нет id сессии — она не стартовала?"
    cmd_start "$name" --resume "$session" "$@"
}

# Разбор JSONL средствами python3: jq в системе может не быть, а python
# в проекте есть заведомо. Формат событий Codex меняется от версии к
# версии, поэтому читаем мягко — неизвестное поле не роняет вывод.
parse_events() {
    python3 - "$1" "${2:-status}" <<'PY'
import json, sys

path, mode = sys.argv[1], sys.argv[2]
session = ""
items = []
tokens = {}
try:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type", "")
            if "thread" in kind and event.get("thread_id"):
                session = event["thread_id"]
            if event.get("session_id"):
                session = event["session_id"]
            usage = event.get("usage") or (event.get("turn") or {}).get("usage")
            if isinstance(usage, dict):
                tokens = usage
            item = event.get("item")
            if isinstance(item, dict):
                items.append(item)
except FileNotFoundError:
    pass

if mode == "session":
    print(session)
    sys.exit(0)

def describe(item):
    kind = item.get("item_type") or item.get("type") or "?"
    if kind in {"command_execution", "command"}:
        text = item.get("command") or ""
    elif kind in {"file_change", "patch"}:
        text = ", ".join(sorted(item.get("changes") or {})) or item.get("path", "")
    elif kind in {"agent_message", "assistant_message", "reasoning"}:
        text = item.get("text") or item.get("summary") or ""
    else:
        text = item.get("text") or ""
    text = " ".join(str(text).split())
    return kind, (text[:110] + "…" if len(text) > 110 else text)

if session:
    print(f"сессия: {session}")
if tokens:
    parts = [f"{key} {value}" for key, value in sorted(tokens.items()) if isinstance(value, int)]
    if parts:
        print("токены: " + ", ".join(parts))
print(f"событий: {len(items)}")
for item in items[-8:]:
    kind, text = describe(item)
    print(f"  · {kind:20} {text}")
PY
}

cmd_status() {
    local name="${1:-}"
    [ -n "$name" ] || name="$(latest_name)" || die "нет ни одного прогона"
    local dir; dir="$(run_dir "$name")"
    [ -d "$dir" ] || die "нет прогона «$name»"

    local state="выполняется"
    if [ -f "$dir/exit" ]; then
        local code; code="$(cat "$dir/exit")"
        [ "$code" = "0" ] && state="завершено, код 0" || state="ЗАВЕРШЕНО С ОШИБКОЙ, код $code"
    elif [ -f "$dir/pid" ] && ! kill -0 "$(cat "$dir/pid")" 2>/dev/null; then
        state="ПРОЦЕСС ИСЧЕЗ, кода возврата нет"
    fi

    local elapsed=""
    if [ -f "$dir/started" ]; then
        elapsed="$(( ($(date +%s) - $(cat "$dir/started")) / 60 )) мин"
    fi
    echo "задача:  $name"
    echo "статус:  $state${elapsed:+, идёт $elapsed}"
    parse_events "$dir/events.jsonl" status
    # id сессии кладём рядом, чтобы `resume` и watch-codex.sh им пользовались.
    parse_events "$dir/events.jsonl" session > "$dir/session"
    [ -s "$dir/last.md" ] && echo "результат готов: $dir/last.md"
    return 0
}

cmd_result() {
    local name="${1:-}"
    [ -n "$name" ] || name="$(latest_name)" || die "нет ни одного прогона"
    local dir; dir="$(run_dir "$name")"
    [ -f "$dir/last.md" ] || die "результата пока нет; см. status $name"
    cat "$dir/last.md"
}

cmd_watch() {
    local name="${1:-}"
    [ -n "$name" ] || name="$(latest_name)" || die "нет ни одного прогона"
    local dir; dir="$(run_dir "$name")"
    local session; session="$(cat "$dir/session" 2>/dev/null || true)"
    if [ -n "$session" ] && [ -x "$ROOT/scripts/watch-codex.sh" ]; then
        exec "$ROOT/scripts/watch-codex.sh" "$session"
    fi
    echo "id сессии ещё не известен, показываю поток событий" >&2
    tail -f "$dir/events.jsonl"
}

cmd_list() {
    [ -d "$RUNS" ] || { echo "прогонов нет"; return 0; }
    local dir name state rows=()
    for dir in "$RUNS"/*/; do
        dir="${dir%/}"
        [ -d "$dir" ] || continue
        name="$(basename "$dir")"
        if [ -f "$dir/exit" ]; then
            state="код $(cat "$dir/exit")"
        elif [ -f "$dir/pid" ] && kill -0 "$(cat "$dir/pid")" 2>/dev/null; then
            state="выполняется"
        else
            state="оборвано"
        fi
        rows+=("$name"$'\t'"$state"$'\t'"$([ -s "$dir/last.md" ] && echo "$dir/last.md" || echo '—')")
    done
    # Выравнивание считает python: `printf %-24s` в bash меряет БАЙТЫ, и на
    # кириллических именах таблица разъезжается вдвое.
    printf '%s\n' "${rows[@]}" | python3 -c '
import sys
rows = [line.rstrip("\n").split("\t") for line in sys.stdin if line.strip()]
head = ["ЗАДАЧА", "СТАТУС", "РЕЗУЛЬТАТ"]
widths = [max(len(row[i]) for row in [head, *rows]) for i in range(3)]
for row in [head, *rows]:
    print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())
'
}

cmd_stop() {
    local name="${1:-}"
    [ -n "$name" ] || die "не задано имя задачи"
    local dir; dir="$(run_dir "$name")"
    [ -f "$dir/pid" ] || die "нет pid у «$name»"
    kill -TERM "-$(cat "$dir/pid")" 2>/dev/null || kill -TERM "$(cat "$dir/pid")" 2>/dev/null || true
    echo "остановлено: $name"
}

case "${1:-}" in
    start)  shift; cmd_start "$@" ;;
    resume) shift; cmd_resume "$@" ;;
    status) shift; cmd_status "${1:-}" ;;
    result) shift; cmd_result "${1:-}" ;;
    watch)  shift; cmd_watch "${1:-}" ;;
    list)   shift; cmd_list ;;
    stop)   shift; cmd_stop "${1:-}" ;;
    -h|--help|help|"") usage ;;
    *) die "неизвестная команда «$1»; см. --help" ;;
esac
