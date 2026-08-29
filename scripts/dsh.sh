#!/usr/bin/env bash
# Запуск dsh с настройкой из этого репозитория.
#
# DSH_HOME переключается на .dsh/ в корне проекта: провайдер, роли по правам,
# патч-слой и скиллы лежат под контролем версий. Ключ не копируется, а
# берётся симлинком из ~/.dsh/.credentials.yaml — в репозиторий он не попадает.
#
#   ./scripts/dsh.sh                 веб-интерфейс на 3080
#   ./scripts/dsh.sh --port 3081     другой порт
#   ./scripts/dsh.sh --dump-config   показать собранное дерево плагинов
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS="${DSH_HARNESS:-/home/vmelnik/deepseek-harness}"
export DSH_HOME="$ROOT/.dsh"

[ -d "$HARNESS" ] || { echo "dsh.sh: нет клона харнесса: $HARNESS" >&2; exit 2; }

# Ключ провайдера: один на все проекты, в репозиторий не едет.
# Имя переменной должно совпадать с apiKeyEnv из .dsh/settings.yaml.
if [ ! -e "$DSH_HOME/.credentials.yaml" ] && [ -f "$HOME/.dsh/.credentials.yaml" ]; then
    ln -s "$HOME/.dsh/.credentials.yaml" "$DSH_HOME/.credentials.yaml"
fi

# Плагины вне бандла base не получают симлинка автоматически: ферму
# profiles/node_modules харнесс наполняет только своими зависимостями.
# Без этих двух строк мост хуков падает при загрузке — причём
# `--dump-config` компонуется успешно и ничего не сообщает.
farm="$DSH_HOME/profiles/node_modules/@deepseek-ai"
if [ -d "$farm" ]; then
    ln -sfn "$HARNESS/packages/hooks/hooks-claude-code"        "$farm/dsh-hooks-claude-code"
    ln -sfn "$HARNESS/packages/hooks/hook-protocol"            "$farm/dsh-hook-protocol"
    ln -sfn "$HARNESS/packages/subagent/subagent-codex"        "$farm/dsh-subagent-codex"
    ln -sfn "$HARNESS/packages/subagent/subagent-claude-code"  "$farm/dsh-subagent-claude-code"
fi

case "${1:-}" in
    -*|"") set -- web "$@" ;;   # без подкоманды поднимаем веб-профиль
esac

cd "$HARNESS"
exec pnpm dsh "$@"
