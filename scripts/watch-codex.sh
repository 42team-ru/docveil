#!/usr/bin/env bash
# Живой просмотр сессии Codex: рассуждения, команды, вывод, расход токенов.
#
# Зачем не `tail -F` по логу вызова: Codex пишет в stdout одним куском в
# самом конце, а rollout-файл сессии пополняется построчно прямо во время
# работы. Смотреть надо его.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSIONS="$ROOT/.codex/sessions"

usage() {
    cat <<'USAGE'
Использование: watch-codex.sh [ОПЦИИ] [ЗАПРОС]

ЗАПРОС — номер из `--list`, UUID сессии, кусок текста из промпта
или ничего (тогда берётся самая свежая).

Опции:
  -l, --list          список сессий и выход (по умолчанию 25 последних)
  -N, --limit N       сколько сессий показать в списке
  -n, --lines N       сколько строк истории показать перед слежением (по умолчанию 40)
  -c, --commands      только команды и их вывод, без рассуждений
  -q, --quiet         только сообщения модели и команды, без вывода команд
  -w, --wide N        сколько строк вывода команды показывать целиком (по умолчанию 12)
  -o, --once          показать и выйти, не следить дальше
  -r, --raw           сырой JSON (для отладки самого скрипта)
  -h, --help          эта справка

Примеры:
  watch-codex.sh                     # следить за текущей сессией
  watch-codex.sh -l                  # какие вообще есть сессии
  watch-codex.sh -c                  # только что он запускает
  watch-codex.sh 3                   # третья сессия из списка --list
  watch-codex.sh -l -N 100           # длинная история
  watch-codex.sh Z1                  # сессия, в промпте которой встречается «Z1»
  watch-codex.sh -o -n 200 | less -R # почитать законченную сессию
USAGE
}

LINES=40
WIDE=12
LIST_LIMIT=25
MODE=full
ONCE=0
RAW=0
QUERY=""

while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        -l|--list) MODE=list; shift ;;
        -c|--commands) MODE=commands; shift ;;
        -q|--quiet) MODE=quiet; shift ;;
        -o|--once) ONCE=1; shift ;;
        -r|--raw) RAW=1; shift ;;
        -n|--lines) LINES="${2:?-n требует число}"; shift 2 ;;
        -N|--limit) LIST_LIMIT="${2:?-N требует число}"; shift 2 ;;
        -w|--wide) WIDE="${2:?-w требует число}"; shift 2 ;;
        --) shift; QUERY="${1:-}"; break ;;
        -*) echo "Неизвестная опция: $1" >&2; usage >&2; exit 2 ;;
        *) QUERY="$1"; shift ;;
    esac
done

if [ ! -d "$SESSIONS" ]; then
    echo "Нет каталога Codex sessions: $SESSIONS" >&2
    exit 1
fi

# Цвета гасим, если вывод уходит не в терминал (в файл, в less без -R, в pipe).
if [ -t 1 ]; then
    C_DIM=$'\033[2m'; C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'
    C_CMD=$'\033[1;36m'; C_OUT=$'\033[0;37m'; C_MSG=$'\033[1;32m'
    C_THINK=$'\033[0;35m'; C_WARN=$'\033[1;33m'; C_ERR=$'\033[1;31m'
    C_HEAD=$'\033[1;34m'
else
    C_DIM=""; C_RESET=""; C_BOLD=""; C_CMD=""; C_OUT=""; C_MSG=""
    C_THINK=""; C_WARN=""; C_ERR=""; C_HEAD=""
fi

# История сессий. Считает python, а не конвейер из jq и head: с
# `set -euo pipefail` связка `jq … | head -1` роняет весь скрипт — head
# закрывает пайп, jq получает SIGPIPE и возвращает ненулевой код. Из-за
# этого `--list` печатал один заголовок и молча выходил (найдено 10.09.2026).
list_sessions() {
    local limit="${1:-25}"
    LIST_LIMIT="$limit" SESSIONS_DIR="$SESSIONS" python3 - "$SESSIONS" <<'PYLIST'
import json, os, re, sys, time

sessions_dir = sys.argv[1]
limit = int(os.environ.get("LIST_LIMIT", "25"))
uuid_re = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

files = []
for root, _dirs, names in os.walk(sessions_dir):
    for name in names:
        if name.startswith("rollout-") and name.endswith(".jsonl"):
            path = os.path.join(root, name)
            try:
                files.append((os.path.getmtime(path), path))
            except OSError:
                pass
files.sort(reverse=True)

BOLD, DIM, WARN, RESET = "\033[1m", "\033[2m", "\033[33m", "\033[0m"
if not sys.stdout.isatty():
    BOLD = DIM = WARN = RESET = ""

def summarize(path):
    """Первое сообщение человека, число команд и время последней записи.

    Служебные блоки (`<skills_instructions>`, `<environment_context>` и
    прочая обвязка) — не задача, а обёртка вокруг неё: если показать их,
    все строки списка будут одинаковыми.
    """
    prompt, commands, last = "", 0, None
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = event.get("payload") or {}
                if payload.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
                    commands += 1
                if event.get("timestamp"):
                    last = event["timestamp"]
                if prompt or payload.get("type") != "message":
                    continue
                if payload.get("role") not in (None, "user"):
                    continue
                content = payload.get("content")
                if isinstance(content, list):
                    text = " ".join(
                        part.get("text") or part.get("input_text") or ""
                        for part in content
                        if isinstance(part, dict)
                    )
                else:
                    text = str(content or "")
                text = " ".join(text.split())
                # Обвязка, а не задача: служебные блоки в угловых скобках и
                # врезка правил проекта, которую Codex подставляет сам.
                if not text or text.startswith("<") or text.startswith("# AGENTS.md"):
                    continue
                prompt = text
    except OSError:
        pass
    return prompt, commands, last

running = os.popen("pgrep -fa 'codex' 2>/dev/null").read()

rows = []
for index, (mtime, path) in enumerate(files[:limit], 1):
    match = uuid_re.search(os.path.basename(path))
    session = match.group(0) if match else "?"
    prompt, commands, _last = summarize(path)
    age = time.time() - mtime
    alive = session[:8] in running or (age < 90 and "codex" in running)
    rows.append((index, session, mtime, commands, prompt, alive))

if not rows:
    print("сессий нет")
    sys.exit(0)

print(f"{BOLD}№   КОГДА         КОМАНД  СЕССИЯ    ЗАДАЧА{RESET}")
for index, session, mtime, commands, prompt, alive in rows:
    when = time.strftime("%d.%m %H:%M", time.localtime(mtime))
    mark = f"{WARN}●{RESET}" if alive else " "
    prompt = prompt or "—"
    if len(prompt) > 62:
        prompt = prompt[:61] + "…"
    print(f"{index:<3} {DIM}{when}{RESET} {mark} {commands:>5}  {session[:8]}  {prompt}")
print()
print(f"{DIM}watch-codex.sh N — смотреть сессию по номеру; можно и по UUID или куску промпта{RESET}")
PYLIST
}

# Путь к сессии по её порядковому номеру из `--list`.
session_by_index() {
    local want="$1"
    find "$SESSIONS" -type f -name 'rollout-*.jsonl' -printf '%T@ %p\n' \
        | sort -nr | sed -n "${want}p" | cut -d' ' -f2-
}

newest() {
    find "$SESSIONS" -type f -name 'rollout-*.jsonl' -printf '%T@ %p\n' \
        | sort -nr | head -1 | cut -d' ' -f2-
}

find_session() {
    if [ -z "$QUERY" ]; then newest; return; fi
    # Номер строки из `--list` — самый быстрый способ выбрать сессию руками.
    if [[ "$QUERY" =~ ^[0-9]+$ ]]; then session_by_index "$QUERY"; return; fi
    if [[ "$QUERY" =~ ^[0-9a-fA-F-]{36}$ ]]; then
        find "$SESSIONS" -type f -name "*${QUERY}.jsonl" -print -quit
        return
    fi
    grep -RIl -- "$QUERY" "$SESSIONS" 2>/dev/null | xargs -r ls -1t | head -1
}

if [ "$MODE" = list ]; then
    printf '%sСессии Codex%s\n\n' "$C_HEAD" "$C_RESET"
    list_sessions "$LIST_LIMIT"
    exit 0
fi

ROLL="$(find_session)"
if [ -z "${ROLL:-}" ] || [ ! -f "$ROLL" ]; then
    echo "Сессия не найдена: ${QUERY:-<последняя>}" >&2
    echo "Посмотреть доступные:  $0 --list" >&2
    exit 1
fi

UUID="$(basename "$ROLL" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')"

if [ "$RAW" = 1 ]; then
    exec tail -n "$LINES" -F "$ROLL"
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "jq не найден — показываю сырой JSON." >&2
    exec tail -n "$LINES" -F "$ROLL"
fi

# ── шапка ────────────────────────────────────────────────────────────────
if pgrep -f "codex exec" >/dev/null 2>&1; then
    STATUS="${C_WARN}● работает${C_RESET}"
else
    STATUS="${C_DIM}○ завершена${C_RESET}"
fi
printf '%s┌─ Codex%s %s\n' "$C_HEAD" "$C_RESET" "$STATUS"
printf '%s│%s  %s\n' "$C_HEAD" "$C_RESET" "$UUID"
printf '%s│%s  %s%s%s\n' "$C_HEAD" "$C_RESET" "$C_DIM" "${ROLL#"$ROOT"/}" "$C_RESET"

# Последний известный расход — полезнее всего понимать, жив ли прогресс.
TOK="$(jq -r 'select(.payload.type=="token_count")
              | "\(.payload.info.total_token_usage.total_tokens // 0)\t\(.payload.info.model_context_window // 0)\t\(.payload.rate_limits.primary.used_percent // 0)"' \
        "$ROLL" 2>/dev/null | tail -1)"
if [ -n "$TOK" ]; then
    IFS=$'\t' read -r used window pct <<<"$TOK"
    printf '%s│%s  токенов: %s%s%s   окно: %s   лимит: %s%%\n' \
        "$C_HEAD" "$C_RESET" "$C_BOLD" "$used" "$C_RESET" "$window" "$pct"
fi
printf '%s└─%s %sCtrl+C — выйти%s\n\n' "$C_HEAD" "$C_RESET" "$C_DIM" "$C_RESET"

# ── поток ────────────────────────────────────────────────────────────────
render() {
    jq --unbuffered -r \
       --arg mode "$MODE" \
       --argjson wide "$WIDE" \
       --arg c_cmd "$C_CMD" --arg c_out "$C_OUT" --arg c_msg "$C_MSG" \
       --arg c_think "$C_THINK" --arg c_dim "$C_DIM" --arg c_reset "$C_RESET" \
       --arg c_err "$C_ERR" --arg c_bold "$C_BOLD" '

    # Текст приходит то строкой, то массивом блоков, то объектом.
    def text_content:
        if type == "string" then .
        elif type == "array" then
            map(if type == "object"
                then (.text // .input_text // .output_text // empty)
                else tostring end) | join("")
        elif type == "object" then (.text // .message // .output // tostring)
        else tostring end;

    def hhmm:
        if . then (.[11:19]) else "        " end;

    # Длинный вывод команды — главная причина, по которой лог нечитаем.
    # Показываем голову и говорим, сколько строк скрыто.
    def clip(n):
        . as $t
        | ($t | split("\n")) as $lines
        | ($lines | length) as $total
        | if $total <= n then $t
          else (($lines[0:n] | join("\n"))
                + "\n" + $c_dim + "  … ещё " + (($total - n) | tostring) + " строк" + $c_reset)
          end;

    def indent($prefix): split("\n") | map($prefix + .) | join("\n");

    (.timestamp | hhmm) as $ts
    |
    if .type == "response_item" then
        if .payload.type == "reasoning" then
            if $mode == "commands" or $mode == "quiet" then empty
            else
                ((.payload.summary // .payload.text // .payload.content // empty) | text_content) as $r
                | if ($r | length) > 0
                  then $c_dim + $ts + " " + $c_think + "🧠 " + ($r | clip(6)) + $c_reset
                  else empty end
            end

        elif (.payload.type == "custom_tool_call" or .payload.type == "function_call") then
            ((.payload.input // .payload.arguments // .payload.command // .payload.name // empty) | text_content) as $cmd
            | if ($cmd | length) > 0
              then "\n" + $c_dim + $ts + " " + $c_cmd + "▶ " + ($cmd | clip(8)) + $c_reset
              else empty end

        elif (.payload.type == "custom_tool_call_output" or .payload.type == "function_call_output") then
            if $mode == "quiet" then empty
            else
                ((.payload.output // .payload.content // empty) | text_content) as $out
                | if ($out | length) > 0
                  then $c_out + ($out | clip($wide) | indent("  ")) + $c_reset
                  else empty end
            end

        elif .payload.type == "message" then
            ((.payload.content // .payload.text // empty) | text_content) as $m
            | if ($m | length) > 0
              then "\n" + $c_msg + "💬 " + $m + $c_reset + "\n"
              else empty end

        else empty end

    elif .type == "event_msg" then
        if .payload.type == "token_count" then
            if $mode == "commands" then empty
            else
                (.payload.info.total_token_usage.total_tokens // 0) as $t
                | (.payload.rate_limits.primary.used_percent // 0) as $p
                | $c_dim + "   ↳ " + ($t | tostring) + " токенов, лимит " + ($p | tostring) + "%" + $c_reset
            end
        elif .payload.type == "error" then
            $c_err + "✖ " + ((.payload.message // .payload) | text_content) + $c_reset
        else empty end

    else empty end
    '
}

if [ "$ONCE" = 1 ]; then
    tail -n "$LINES" "$ROLL" | render
else
    tail -n "$LINES" -F "$ROLL" | render
fi
