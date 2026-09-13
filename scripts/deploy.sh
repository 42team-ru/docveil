#!/usr/bin/env bash
#
# Развернуть стенд DocVeil одной командой.
#
#   ./scripts/deploy.sh check     # только проверки окружения, ничего не меняет
#   ./scripts/deploy.sh up        # проверки → .env.prod → сборка → запуск → админ
#   ./scripts/deploy.sh update    # пересобрать и перезапустить после git pull
#   ./scripts/deploy.sh status    # что поднято и в каком состоянии здоровья
#   ./scripts/deploy.sh logs      # живая лента логов
#   ./scripts/deploy.sh admin     # завести или сбросить администратора
#   ./scripts/deploy.sh down      # остановить (данные в томах остаются)
#
# Флаги: --yes (не задавать вопросов, брать значения из окружения и дефолты),
#        --no-build (не пересобирать образы), --env-file FILE,
#        --demo (взять готовое окружение deploy/env.demo с фиксированными паролями
#        из README — стенд для показа, не для настоящих документов),
#        --images[=ТЕГ] (тянуть готовые образы из ghcr.io/42team-ru вместо сборки;
#        без тега — latest). Ограничение режима --images описано в docs/DEPLOY.md:
#        опубликованный образ фронта собран без VITE_BACKEND_PROD_URL и ходит в
#        https://42team.ru, поэтому на своём домене фронт всё равно собирается
#        локально.
#
# Скрипт намеренно идемпотентен: повторный `up` не перегенерирует секреты,
# не сбросит пароль администратора и не потеряет тома с данными.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env.prod"
ASSUME_YES=0
DO_BUILD=1
# Режим готовых образов: не собирать, а тянуть из GHCR. Включается --images.
USE_REGISTRY=0
# Демо-режим: готовое окружение из deploy/env.demo, без единого вопроса.
DEMO_MODE=0
REGISTRY_TAG="latest"
REGISTRY="ghcr.io/42team-ru"

# Цвета только когда вывод идёт в терминал: в логах CI escape-последовательности
# превращают сообщение об ошибке в нечитаемый мусор.
if [ -t 1 ]; then
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'
    C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
    C_RED=''; C_GREEN=''; C_YELLOW=''; C_BOLD=''; C_OFF=''
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_YELLOW" "$C_OFF" "$*"; }
bad()  { printf '  %s✗%s %s\n' "$C_RED" "$C_OFF" "$*"; }
head1() { printf '\n%s%s%s\n' "$C_BOLD" "$*" "$C_OFF"; }
die()  { printf '\n%sОшибка:%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

PREFLIGHT_FAILED=0

# ---------------------------------------------------------------- проверки --

check_docker() {
    head1 "Docker"

    if ! command -v docker >/dev/null 2>&1; then
        bad "docker не найден в PATH"
        say "    Установка: https://docs.docker.com/engine/install/"
        say "    Ubuntu/Debian: curl -fsSL https://get.docker.com | sh"
        PREFLIGHT_FAILED=1
        return
    fi
    ok "docker: $(docker --version | sed 's/,.*//')"

    # `docker info` проверяет сразу две вещи: демон запущен и текущий
    # пользователь имеет право с ним говорить. Разделяем причины: «нет прав» и
    # «демон лежит» чинятся по-разному, а сообщение у docker одинаковое.
    if ! docker info >/dev/null 2>&1; then
        bad "демон Docker недоступен"
        if ! id -nG 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
            say "    Похоже, пользователь $(id -un) не в группе docker:"
            say "      sudo usermod -aG docker $(id -un) && newgrp docker"
        fi
        say "    Либо демон не запущен:  sudo systemctl start docker"
        PREFLIGHT_FAILED=1
        return
    fi
    ok "демон Docker отвечает"

    # Плагин v2 (`docker compose`), а не legacy-бинарь `docker-compose`: файл
    # использует спецификацию compose, которую v1 не понимает.
    if ! docker compose version >/dev/null 2>&1; then
        bad "плагин 'docker compose' (v2) не установлен"
        if command -v docker-compose >/dev/null 2>&1; then
            say "    Найден старый docker-compose v1 — этого файла он не поймёт."
        fi
        say "    Ubuntu/Debian: sudo apt-get install docker-compose-plugin"
        PREFLIGHT_FAILED=1
        return
    fi
    ok "compose: $(docker compose version --short 2>/dev/null || echo v2)"
}

check_resources() {
    head1 "Ресурсы машины"

    local cores
    cores="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
    if [ "$cores" -ge 4 ]; then
        ok "CPU: ${cores} ядер"
    elif [ "$cores" -ge 2 ]; then
        warn "CPU: ${cores} ядра — хватит на демонстрацию, но параллельные прогоны будут ждать друг друга"
    else
        warn "CPU: ${cores} — мало; рекомендуется 4 ядра"
    fi

    # MemAvailable честнее MemFree: учитывает кэш, который ядро отдаст.
    # Своп считается вместе с ней: пик приходится на СБОРКУ (yarn/vite), а
    # сборке своп годится — она переживает страничный обмен, в отличие от
    # прогона документа. Без учёта свопа проверка блокировала машину 2/4,
    # на которой стенд работает (замер 14.09.2026: MemAvailable 3462 МиБ,
    # то есть отказ был из-за 38 МиБ разницы с порогом).
    local mem_mb=0 swap_mb=0
    if [ -r /proc/meminfo ]; then
        mem_mb=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
        swap_mb=$(awk '/SwapTotal/ {print int($2/1024)}' /proc/meminfo)
    fi
    local total_mb=$((mem_mb + swap_mb))
    local swap_note=""
    [ "$swap_mb" -gt 0 ] && swap_note=" (+${swap_mb} МиБ свопа)"

    if [ "$mem_mb" -eq 0 ]; then
        warn "не удалось прочитать объём памяти — пропускаю проверку"
    elif [ "$mem_mb" -ge 7000 ]; then
        ok "ОЗУ доступно: ${mem_mb} МиБ${swap_note}"
    elif [ "$total_mb" -ge 3000 ]; then
        warn "ОЗУ доступно: ${mem_mb} МиБ${swap_note} — стенд поднимется, но держите 1–2 прогона одновременно"
        if [ "$mem_mb" -lt 4000 ] && [ "$swap_mb" -lt 2000 ] && [ "$USE_REGISTRY" -eq 0 ]; then
            say "    Сборка фронта тут будет впритык. Готовые образы: --images"
            say "    Либо добавьте своп на время сборки:"
            say "      sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile"
            say "      sudo mkswap /swapfile && sudo swapon /swapfile"
        fi
    else
        bad "ОЗУ доступно: ${mem_mb} МиБ${swap_note} — мало даже для одного прогона"
        say "    Один прогон занимает около 0,55 ГиБ, плюс Postgres, MinIO и Caddy."
        say "    Добавьте своп и повторите:"
        say "      sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile"
        say "      sudo mkswap /swapfile && sudo swapon /swapfile"
        PREFLIGHT_FAILED=1
    fi

    local free_gb
    free_gb=$(df -Pk "$REPO_ROOT" 2>/dev/null | awk 'NR==2 {print int($4/1024/1024)}')
    if [ -z "$free_gb" ]; then
        warn "не удалось оценить свободное место"
    elif [ "$free_gb" -ge 20 ]; then
        ok "свободно на диске: ${free_gb} ГиБ"
    elif [ "$free_gb" -ge 10 ]; then
        warn "свободно на диске: ${free_gb} ГиБ — образы и документы займут больше за неделю работы"
    else
        bad "свободно на диске: ${free_gb} ГиБ — образы backend и frontend не соберутся"
        PREFLIGHT_FAILED=1
    fi
}

check_ports() {
    head1 "Порты"

    # Занятый 80/443 — самая частая причина падения `up` на чужом сервере,
    # причём падает оно уже после сборки образов, потратив пять минут.
    local busy=0 port
    for port in 80 443; do
        if port_busy "$port"; then
            # Свой же Caddy, поднятый прошлым разом, — не конфликт.
            if compose ps --status running 2>/dev/null | grep -q caddy; then
                ok "порт ${port} занят нашим же Caddy (перезапуск это переживёт)"
                continue
            fi
            bad "порт ${port} уже занят другим процессом"
            busy=1
        else
            ok "порт ${port} свободен"
        fi
    done
    if [ "$busy" -eq 1 ]; then
        say "    Посмотреть, кем:  sudo ss -tlnp 'sport = :80'"
        say "    Обычно это системный nginx или apache:  sudo systemctl stop nginx"
        PREFLIGHT_FAILED=1
    fi
}

port_busy() {
    local port="$1"
    if command -v ss >/dev/null 2>&1; then
        ss -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tln 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"
    else
        return 1  # нечем проверить — не выдумываем результат
    fi
}

check_tools() {
    head1 "Вспомогательные утилиты"

    if command -v openssl >/dev/null 2>&1; then
        ok "openssl — есть, секреты сгенерируются им"
    else
        warn "openssl не найден — секреты возьмутся из /dev/urandom"
    fi
    if command -v git >/dev/null 2>&1; then
        ok "git — есть (нужен для ./scripts/deploy.sh update)"
    else
        warn "git не найден — команда update работать не будет"
    fi
}

check_files() {
    head1 "Файлы репозитория"
    local missing=0 path
    for path in "$COMPOSE_FILE" deploy/Caddyfile backend/Dockerfile frontend/Dockerfile; do
        if [ -f "$path" ]; then
            ok "$path"
        else
            bad "нет файла $path"
            missing=1
        fi
    done
    [ "$missing" -eq 0 ] || PREFLIGHT_FAILED=1
}

preflight() {
    say "${C_BOLD}Проверка окружения${C_OFF}"
    check_docker
    check_files
    check_resources
    check_ports
    check_tools

    if [ "$PREFLIGHT_FAILED" -eq 1 ]; then
        die "окружение не готово — почините отмеченное красным и повторите."
    fi
    head1 "Окружение готово."
}

# ------------------------------------------------------------------ секреты --

random_secret() {
    local bytes="${1:-32}"
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$bytes"
    else
        # tr выкидывает всё, кроме букв и цифр: спецсимволы в пароле ломают
        # строку подключения к Postgres, собираемую в compose без экранирования.
        LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c $((bytes * 2))
        echo
    fi
}

ask() {
    # ask ПЕРЕМЕННАЯ "вопрос" "значение по умолчанию"
    local var="$1" prompt="$2" default="${3:-}" answer=""
    # Значение из окружения сильнее вопроса: так разворачивается CI.
    if [ -n "${!var:-}" ]; then
        printf '%s\n' "${!var}"
        return
    fi
    if [ "$ASSUME_YES" -eq 1 ] || [ ! -t 0 ]; then
        printf '%s\n' "$default"
        return
    fi
    if [ -n "$default" ]; then
        read -r -p "  ${prompt} [${default}]: " answer </dev/tty
    else
        read -r -p "  ${prompt}: " answer </dev/tty
    fi
    printf '%s\n' "${answer:-$default}"
}

create_env_file() {
    if [ -f "$ENV_FILE" ]; then
        ok "${ENV_FILE} уже есть — существующие секреты не трогаю"
        return
    fi

    if [ "$DEMO_MODE" -eq 1 ]; then
        head1 "Демонстрационный стенд"
        cp deploy/env.demo "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        # Адрес машины подставляется здесь, а не в шаблоне: в шаблоне лежит
        # localhost, и с чужого устройства такой стенд не открылся бы.
        local address
        address="http://$(host_address)"
        sed -i "s|^PUBLIC_URL=.*|PUBLIC_URL=${address}|" "$ENV_FILE"
        ok "окружение взято из deploy/env.demo, адрес — ${address}"
        warn "пароли стенда опубликованы в README: настоящие документы сюда не загружать"
        return
    fi

    head1 "Настройка стенда (${ENV_FILE})"
    say "  Enter — принять значение в скобках."

    local domain site_address public_url cookie_secure acme_email
    domain="$(ask DOMAIN 'Домен стенда (пусто — работать по IP без TLS)' '')"
    if [ -n "$domain" ]; then
        site_address="$domain"
        public_url="https://${domain}"
        cookie_secure="true"
        acme_email="$(ask ACME_EMAIL 'Почта для Let'\''s Encrypt' "admin@${domain}")"
    else
        # Без домена сертификат выпустить не на что. COOKIE_SECURE=false
        # обязателен: браузер не отдаёт Secure-cookie по http, и refresh-токен
        # умрёт молча при первой же перезагрузке вкладки.
        site_address=":80"
        public_url="http://$(host_address)"
        cookie_secure="false"
        acme_email="admin@localhost"
        warn "без домена: http без TLS, COOKIE_SECURE=false — для демонстрации, не для рабочих данных"
    fi

    local admin_email admin_password llm gigachat
    admin_email="$(ask ADMIN_EMAIL 'E-mail администратора' 'admin@example.ru')"
    admin_password="$(ask ADMIN_PASSWORD 'Пароль администратора (пусто — сгенерировать)' '')"
    [ -n "$admin_password" ] || admin_password="$(random_secret 9)"

    gigachat="$(ask GIGACHAT_CREDENTIALS 'Ключ авторизации GigaChat (пусто — работать без модели)' '')"
    if [ -n "$gigachat" ]; then llm="gigachat"; else llm="fake"; fi

    umask 077
    cat > "$ENV_FILE" <<EOF
# Создан ./scripts/deploy.sh $(date '+%Y-%m-%d %H:%M:%S').
# Секреты сгенерированы случайно. Файл не попадает в git (.gitignore: .env.*).
# Карта полей и неинтерактивное развёртывание — deploy/env.prod.example.

SITE_ADDRESS=${site_address}
PUBLIC_URL=${public_url}
ACME_EMAIL=${acme_email}
COOKIE_SECURE=${cookie_secure}

POSTGRES_USER=masker
POSTGRES_PASSWORD=$(random_secret 24)
POSTGRES_DB=masker
JWT_SECRET=$(random_secret 32)
MINIO_ROOT_USER=masker
MINIO_ROOT_PASSWORD=$(random_secret 24)
MINIO_BUCKET=documents

ADMIN_EMAIL=${admin_email}
ADMIN_PASSWORD=${admin_password}
ADMIN_FULL_NAME=${ADMIN_FULL_NAME:-Администратор}

MASKER_OCR=tesseract
MASKER_LLM=${llm}
GIGACHAT_CREDENTIALS=${gigachat}
MASKER_LLM_GIGACHAT_SCOPE=${MASKER_LLM_GIGACHAT_SCOPE:-GIGACHAT_API_PERS}
MASKER_LLM_GIGACHAT_CA_BUNDLE=
OPENROUTER_API_KEY=

BACKEND_MEMORY_LIMIT=3g
BACKEND_CPU_LIMIT=4
POSTGRES_MEMORY_LIMIT=1g
MINIO_MEMORY_LIMIT=1g
FRONTEND_MEMORY_LIMIT=256m
CADDY_MEMORY_LIMIT=256m
EOF
    chmod 600 "$ENV_FILE"
    ok "создан ${ENV_FILE} (права 600, секреты внутри)"
}

host_address() {
    # Внешний адрес нужен ровно для подсказки в конце и для CORS без домена.
    hostname -I 2>/dev/null | awk '{print $1}' || echo localhost
}

env_value() {
    # Читаем из файла, а не из окружения: в окружении может лежать дев-значение.
    awk -F= -v key="$1" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

# -------------------------------------------------------------- развёртывание --

compose() {
    # BACKEND_IMAGE/FRONTEND_IMAGE приходят из окружения (режим --images) и
    # перекрывают дефолты `:local` в compose-файле.
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# Готовый образ бэкенда универсален: адрес API в него не вшивается. Образ
# фронта — нет, поэтому он собирается локально даже в режиме --images, иначе
# стенд молча стучался бы в чужой домен из релизной сборки.
pull_images() {
    head1 "Готовые образы из ${REGISTRY}"
    export BACKEND_IMAGE="${REGISTRY}/docveil-backend:${REGISTRY_TAG}"
    if ! compose pull backend; then
        bad "не удалось получить ${BACKEND_IMAGE}"
        say "    Образы приватные? Нужен вход:  docker login ghcr.io -u <логин>"
        say "    Или соберите локально, без --images."
        exit 1
    fi
    ok "бэкенд: ${BACKEND_IMAGE}"

    local public_url
    public_url="$(env_value PUBLIC_URL)"
    if [ "$public_url" = "https://42team.ru" ]; then
        export FRONTEND_IMAGE="${REGISTRY}/docveil-frontend:${REGISTRY_TAG}"
        compose pull frontend || die "не удалось получить ${FRONTEND_IMAGE}"
        ok "фронтенд: ${FRONTEND_IMAGE}"
        return
    fi
    warn "фронтенд собирается локально: в релизном образе вшит https://42team.ru,"
    say "    а этот стенд живёт на ${public_url}"
    compose build --pull frontend || die "сборка фронтенда не прошла"
}

build_images() {
    if [ "$USE_REGISTRY" -eq 1 ]; then
        pull_images
        return
    fi
    if [ "$DO_BUILD" -eq 0 ]; then
        warn "сборка пропущена (--no-build)"
        return
    fi
    head1 "Сборка образов"
    say "  Первый раз это 5–10 минут: ставится tesseract, зависимости Python и сборка фронта."
    # Отдельная обработка вместо падения по `set -e`: самая частая причина —
    # недоступный реестр образов, и «failed to fetch anonymous token» посреди
    # вывода buildkit читается как поломка проекта, хотя чинится повтором.
    if ! compose build --pull; then
        bad "сборка не прошла"
        say "    Если в выводе выше упоминается auth.docker.io, registry-1.docker.io"
        say "    или 'failed to fetch anonymous token' — это реестр образов, а не проект."
        say "    Повторите команду; при устойчивой недоступности пропишите зеркало в"
        say "    /etc/docker/daemon.json (registry-mirrors) и перезапустите демон."
        exit 1
    fi
}

start_stack() {
    head1 "Запуск"
    compose up -d
}

wait_for_health() {
    local service="$1" timeout="${2:-240}" waited=0 cid state
    printf '  жду %s' "$service"
    while [ "$waited" -lt "$timeout" ]; do
        cid="$(compose ps -q "$service" 2>/dev/null || true)"
        if [ -n "$cid" ]; then
            state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo unknown)"
            case "$state" in
                healthy|running)
                    printf '\n'; ok "$service: $state"; return 0 ;;
                exited|dead)
                    printf '\n'; bad "$service упал (состояние: $state)"
                    compose logs --tail 40 "$service"
                    return 1 ;;
            esac
        fi
        printf '.'
        sleep 3
        waited=$((waited + 3))
    done
    printf '\n'
    bad "$service не поднялся за ${timeout} с"
    compose logs --tail 40 "$service"
    return 1
}

seed_admin() {
    local reset="${1:-}"
    local email password full_name
    email="$(env_value ADMIN_EMAIL)"
    password="$(env_value ADMIN_PASSWORD)"
    full_name="$(env_value ADMIN_FULL_NAME)"
    [ -n "$email" ] && [ -n "$password" ] || die "в ${ENV_FILE} нет ADMIN_EMAIL/ADMIN_PASSWORD"

    head1 "Администратор"
    # Пароль передаётся разово в exec, а не живёт в окружении сервиса backend:
    # переменные сервиса видны в `docker inspect` любому, кто дотянулся до демона.
    compose exec -T \
        -e ADMIN_EMAIL="$email" \
        -e ADMIN_PASSWORD="$password" \
        -e ADMIN_FULL_NAME="${full_name:-Администратор}" \
        backend python scripts/seed_admin.py ${reset:+--reset-password}

    seed_demo_user "$reset"
}

# Аккаунт без прав администратора заводится, только если он описан в
# окружении: на рабочем стенде лишних учётных записей быть не должно.
seed_demo_user() {
    local reset="${1:-}"
    local email password full_name
    email="$(env_value DEMO_USER_EMAIL)"
    password="$(env_value DEMO_USER_PASSWORD)"
    [ -n "$email" ] && [ -n "$password" ] || return 0
    full_name="$(env_value DEMO_USER_FULL_NAME)"

    compose exec -T \
        -e ADMIN_EMAIL="$email" \
        -e ADMIN_PASSWORD="$password" \
        -e ADMIN_FULL_NAME="${full_name:-Демонстрационный пользователь}" \
        backend python scripts/seed_admin.py --role user ${reset:+--reset-password}
}

summary() {
    local public_url site_address
    public_url="$(env_value PUBLIC_URL)"
    site_address="$(env_value SITE_ADDRESS)"

    head1 "Стенд поднят"
    say "  Адрес:      ${public_url}"
    say "  API:        ${public_url}/api"
    say "  Swagger:    ${public_url}/docs"
    say "  Админ:      $(env_value ADMIN_EMAIL)  /  $(env_value ADMIN_PASSWORD)"
    if [ -n "$(env_value DEMO_USER_EMAIL)" ]; then
        say "  Аккаунт:    $(env_value DEMO_USER_EMAIL)  /  $(env_value DEMO_USER_PASSWORD)"
    fi
    say ""
    say "  Пароли лежат в ${ENV_FILE} (права 600). Сохраните их отдельно."
    if [ "$site_address" = ":80" ]; then
        say ""
        warn "Стенд работает по http без TLS. Для публичного доступа перезапустите"
        say "    с доменом: удалите ${ENV_FILE} и выполните ./scripts/deploy.sh up"
    fi
    if [ "$(env_value MASKER_LLM)" = "fake" ]; then
        say ""
        warn "MASKER_LLM=fake — роли сторон определяются эвристикой, живой модели нет."
        say "    Ключ GigaChat дописывается в ${ENV_FILE} (GIGACHAT_CREDENTIALS),"
        say "    затем: ./scripts/deploy.sh update"
    fi
    say ""
    say "  Логи:       ./scripts/deploy.sh logs"
    say "  Состояние:  ./scripts/deploy.sh status"
}

cmd_up() {
    preflight
    create_env_file
    build_images
    start_stack
    # Порядок ожидания — снизу вверх по зависимостям: бессмысленно ждать
    # Caddy, пока бэкенд накатывает миграции.
    wait_for_health postgres 60 || die "Postgres не поднялся"
    wait_for_health backend 300 || die "бэкенд не поднялся — смотрите логи выше"
    wait_for_health frontend 120 || die "фронтенд не поднялся"
    wait_for_health caddy 60 || die "Caddy не поднялся"
    seed_admin
    summary
}

cmd_update() {
    [ -f "$ENV_FILE" ] || die "нет ${ENV_FILE} — сначала ./scripts/deploy.sh up"
    preflight
    build_images
    start_stack
    wait_for_health backend 300 || die "бэкенд не поднялся после обновления"
    head1 "Обновлено."
    compose ps
}

usage() {
    sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

main() {
    local command=""
    while [ $# -gt 0 ]; do
        case "$1" in
            check|up|update|status|logs|admin|down) command="$1" ;;
            --yes|-y) ASSUME_YES=1 ;;
            --no-build) DO_BUILD=0 ;;
            --demo) DEMO_MODE=1; ASSUME_YES=1 ;;
            --images) USE_REGISTRY=1 ;;
            --images=*) USE_REGISTRY=1; REGISTRY_TAG="${1#--images=}" ;;
            --env-file) shift; ENV_FILE="${1:?--env-file требует путь}" ;;
            --reset-password) RESET_PASSWORD=1 ;;
            -h|--help) usage; exit 0 ;;
            *) die "неизвестный аргумент: $1 (см. --help)" ;;
        esac
        shift
    done

    case "${command:-up}" in
        check)  preflight ;;
        up)     cmd_up ;;
        update) cmd_update ;;
        status) compose ps ;;
        logs)   compose logs -f --tail 100 ;;
        admin)  seed_admin "${RESET_PASSWORD:-}" ;;
        down)   compose down; say "Остановлено. Данные остались в томах docveil_*." ;;
    esac
}

main "$@"
