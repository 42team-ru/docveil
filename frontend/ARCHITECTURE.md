# Архитектура

`triema-frontend` — фронтенд на React Router v8 в **framework mode** с кодовой базой,
организованной по **Feature-Sliced Design**. Документ описывает слои, границы между ними,
поток данных и сборку. Правила UI вынесены в `AGENTS.md`, генерация API — в `orval.md`.

## Стек

| Слой | Технология |
| --- | --- |
| Роутинг и SSR | `react-router` v8 + `@react-router/dev` (framework mode) |
| Сборка | Vite 8, `@react-router/dev/vite`, `@tailwindcss/vite` |
| UI | Astryx (`@astryxdesign/core`, `theme-neutral`) + Tailwind 4 (только token-backed утилиты) |
| Стили низкого уровня | StyleX (`@stylexjs/stylex`) — транзитивно через Astryx |
| HTTP | axios + сгенерированный Orval-клиент (`client: react-query`) |
| Состояние | zustand (клиентское), react-query (серверное) |
| Валидация | zod |
| Раздача в проде | nginx (см. «Сборка и деплой») |

## Дерево каталогов

```
src/
├── app/                    # инициализация приложения (React Router appDirectory)
│   ├── root.tsx            # <html>, Theme-провайдер, links, ErrorBoundary
│   ├── routes.ts           # декларация карты роутов
│   ├── routes/             # роут-модули: meta / loader / action / рендер страницы
│   │   ├── home/
│   │   └── auth/
│   └── styles/app.css      # reset + astryx.css + theme.css
├── pages/                  # экраны: композиция features/entity/shared в целую страницу
│   ├── home/home-page.tsx
│   └── auth/
├── features/               # пользовательские сценарии (форма логина, фильтр, действие)
├── entity/                 # бизнес-сущности: модель + её UI-представление
├── shared/                 # переиспользуемое, без знания о домене
│   ├── api/
│   │   ├── generated/core/ # вывод Orval — не редактировать руками
│   │   ├── mutators/authMutator.ts
│   │   └── schemas/        # локальные снапшоты OpenAPI (опционально)
│   └── ui/                 # обёртки над Astryx, общие UI-примитивы
└── themes/neutral/         # тема Astryx: токены + реестр иконок
```

`src/themes` намеренно вне FSD-слоёв: это конфигурация дизайн-системы, а не код приложения.
Подключается в `root.tsx` через `<Theme theme={neutralTheme}>`.

## Границы слоёв

Импорты идут **строго вниз**:

```
app → pages → features → entity → shared
```

| Слой | Может импортировать | Не может |
| --- | --- | --- |
| `app` | всё | — |
| `pages` | `features`, `entity`, `shared` | `app`, другие `pages` |
| `features` | `entity`, `shared` | `app`, `pages`, другие `features` |
| `entity` | `shared` | всё выше, другие `entity` |
| `shared` | только внешние пакеты | любой слой приложения |

Горизонтальные импорты (слайс → соседний слайс того же слоя) запрещены: общий код
поднимается в слой ниже. Автоматической проверки (`eslint-plugin-boundaries`) нет —
контроль ручной.

Слои `features` и `entity` пока пустые: проект в стадии каркаса. Первый бизнес-сценарий
должен создать их, а не расползтись по `pages`.

Обрати внимание: слой назван `entity` (единственное число), не канонические `entities`.
Так уже заведено — новые каталоги называй так же.

## Роутинг

Framework mode, `appDirectory: "./src/app"` (`react-router.config.ts`).
Роуты объявляются явно в `src/app/routes.ts` — не по файловой конвенции:

```ts
export default [index("routes/home/home.tsx")] satisfies RouteConfig;
```

Разделение ответственности:

- **`src/app/routes/` — тонкий адаптер к роутеру.** Здесь живут `meta`, `links`,
  `loader`/`action`, `ErrorBoundary` и рендер одного компонента страницы.
- **`src/pages/` — сама страница.** Ничего не знает о роутере; получает данные пропсами
  или хуками.

Типы роут-модулей генерирует `react-router typegen` в `.react-router/types` и импортируются
как `import type { Route } from "./+types/root"`. Каталог в `.gitignore` — после изменения
`routes.ts` нужен `yarn typecheck` (он вызывает typegen), иначе типы разъедутся.

`root.tsx` задаёт `<html lang="ru">`, предзагружает шрифт Inter с Google Fonts и оборачивает
дерево в `<Theme theme={neutralTheme}>`. `QueryClientProvider` здесь пока не подключён —
его нужно добавить вместе с `@tanstack/react-query` до первого использования Orval-хуков.

## Слой данных

### Генерация клиента

Orval читает OpenAPI-схему с работающего бэкенда и генерирует в
`src/shared/api/generated/core` типы, хуки react-query и модели — в режиме `tags-split`
(файл на каждый тег OpenAPI). Каталог не закоммичен и создаётся при `yarn orval`, поэтому
**сборка требует доступного бэкенда**.

Выбор окружения — `ORVAL_BACKEND_ENV=dev|prod`, URL берутся из `VITE_BACKEND_DEV_URL` /
`VITE_BACKEND_PROD_URL`. Подробности и типовые ошибки — в `orval.md`.

### Транспорт: `authMutator`

Весь трафик генерированного клиента идёт через `src/shared/api/mutators/authMutator.ts` —
единственная точка, где можно менять поведение HTTP. Что он делает:

- **Два axios-инстанса.** `clientApi` — для публичных эндпоинтов (`/auth/login`,
  `/auth/register`, проверки username/email); `clientApiWithAuth` — для всего остального.
  Выбор по списку `PUBLIC_AUTH_PATHS`.
- **Куки-сессия.** `withCredentials: true`; токены в JS не хранятся.
- **Прозрачный refresh.** На 401 (кроме самого `/auth/refresh`) один раз дёргается
  `POST /auth/refresh` и запрос повторяется. Параллельные 401 разделяют один in-flight
  промис через `refreshPromise`, повтор ограничен `MAX_REFRESH_RETRIES = 1`.
- **Выход из сессии — событием.** Если refresh не удался, в `window` летит
  `CustomEvent("auth:unauthorized")`. Слушателя пока нет — его должен повесить будущий
  auth-слой (редирект на логин, сброс стора); мутатор про роутер ничего не знает.
- **Нормализация ошибок.** Ответы приводятся к `ErrorType` с плоскими `detail` и `status`;
  массив ошибок валидации FastAPI-стиля склеивается в строку.
- **Нормализация URL.** Абсолютные префиксы из сгенерированного кода (`localhost:8080`,
  `https://42team.ru/api`) срезаются, чтобы работал `baseURL` текущего окружения.
- **Мост fetch и axios.** Orval передаёт payload то как `body`, то как `data`, а заголовки —
  в формате `HeadersInit`; мутатор приводит это к axios-конфигу и возвращает обратно
  fetch-подобный объект (`{ data, status, headers: Headers }`).

Базовый URL выбирается по `import.meta.env.MODE` (`production`/`remote` → prod), с
хардкод-фолбэками на `http://localhost:8080` и `https://42team.ru/api`.

### Состояние

- **Серверное** — react-query через Orval-хуки. Никаких ручных `useEffect` + `axios`.
- **Клиентское** — zustand-сторы. Место стора: `entity/<name>/model` для доменного
  состояния, `features/<name>/model` для состояния сценария. Глобальных сторов в `app` быть
  не должно.
- **Валидация форм и внешних данных** — zod. Типы ответов API берутся из Orval, дублировать
  их схемами не нужно.

## Стилизация и тема

Три уровня, строго в этом порядке:

1. **Пропсы компонентов Astryx** — основной инструмент вёрстки и отступов.
2. **Token-backed Tailwind-утилиты** (`bg-surface`, `text-primary`, `rounded-lg`) — когда
   пропсов не хватает.
3. **Тема** (`src/themes/neutral`) — для брендовых значений. Переопределять `--color-*` в
   `:root` нельзя.

`src/app/styles/app.css` подключает `reset.css`, `astryx.css` и `theme.css` — без этих трёх
импортов компоненты рендерятся без стилей.

Тема `neutral` — грейскейл-основа плюс категориальная палитра, выведенная в OKLCH; все
насыщенные стопы проходят WCAG AA к своему тексту. Иконки регистрируются отдельно в
`src/themes/neutral/icons.tsx`.

Запрещено: `<div>`/`<span>` для раскладки, инлайновый `style`, собственные `.css`/`@apply`,
произвольные значения (`bg-[#fff]`, `p-[13px]`). Полный чеклист — в `AGENTS.md`.

## Сборка и деплой

```
yarn orval   ->  генерация клиента из OpenAPI (нужен живой бэкенд)
yarn build   ->  build/client (ассеты) + build/server (SSR-бандл при ssr: true)
```

`Dockerfile` — трёхстадийный: `deps` (yarn install по lockfile) → `build` (orval + build,
backend URL приходят через `--build-arg`) → `nginx:alpine` со статикой и `nginx.conf`
(SPA-fallback на `index.html`, годовой кэш для хешированных ассетов).

**Нерешённое противоречие:** `react-router.config.ts` объявляет `ssr: true`, а Docker-образ
раздаёт только `build/client` — при включённом SSR там нет `index.html`, и nginx отдавать
нечего. Нужно определиться:

- **SPA** — поставить `ssr: false`, текущий Dockerfile и nginx.conf подходят как есть;
- **SSR** — финальный образ на `node:22-alpine` с `yarn start`
  (`react-router-serve ./build/server/index.js`), nginx остаётся только прокси.

До этого выбора не стоит писать `loader`/`action`, полагающиеся на серверное выполнение.

## Соглашения

- **Файлы** — kebab-case (`home-page.tsx`), **компоненты** — PascalCase.
- Слайс — каталог; при росте делится на `ui/`, `model/`, `api/`, `lib/`.
- Тексты интерфейса — русские, `<html lang="ru">`.
- Инструментов качества (ESLint, Prettier, тесты) в проекте нет. Единственная проверка —
  `yarn typecheck`; TypeScript в `strict`.
