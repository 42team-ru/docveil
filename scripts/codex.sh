#!/usr/bin/env bash
# Запуск Codex с настройкой из этого репозитория.
#
# CODEX_HOME переключается на .codex/ в корне проекта: роли агентов, профили
# и модели лежат под контролем версий и одинаковы у всей команды.
# Логин переиспользуется из ~/.codex — заново входить не нужно.
#
#   ./scripts/codex.sh                 обычная сессия (gpt-5.5, xhigh)
#   ./scripts/codex.sh -p runner       дешёвый исполнитель
#   ./scripts/codex.sh exec "..."      неинтерактивно
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export CODEX_HOME="$ROOT/.codex"

# Учётные данные не копируем, а ссылаемся: один логин на все проекты,
# и ключ не попадает в репозиторий.
if [ ! -e "$CODEX_HOME/auth.json" ] && [ -f "$HOME/.codex/auth.json" ]; then
    ln -s "$HOME/.codex/auth.json" "$CODEX_HOME/auth.json"
fi

# Опечатка в имени профиля Codex'ом не отлавливается: `-p runer` молча
# запустит базовый gpt-5.5 на xhigh, и это заметно только по счёту.
# Проверяем сами.
for i in "$@"; do
    case "${prev:-}" in
        -p|--profile)
            if [ ! -f "$CODEX_HOME/$i.config.toml" ]; then
                echo "codex.sh: нет профиля '$i'." >&2
                echo "Доступны: $(ls "$CODEX_HOME"/*.config.toml 2>/dev/null \
                    | xargs -n1 basename 2>/dev/null | sed 's/\.config\.toml//' | tr '\n' ' ')" >&2
                exit 2
            fi
            ;;
    esac
    prev="$i"
done

# MCP-сервер context7 подключается ключом из окружения, а не из файла в репозитории.
extra=()
if [ -n "${CONTEXT7_API_KEY:-}" ]; then
    extra+=(
        -c 'mcp_servers.context7.type="http"'
        -c 'mcp_servers.context7.url="https://mcp.context7.com/mcp"'
        -c "mcp_servers.context7.http_headers.CONTEXT7_API_KEY=\"${CONTEXT7_API_KEY}\""
    )
fi

exec codex "${extra[@]}" "$@"
