# CLAUDE.md

Инструкции для Claude Code по работе с `triema-frontend`.

## Что это

SPA/SSR-фронтенд на **React Router v8 (framework mode)** + **React 19** + **Vite 8**,
UI собирается на дизайн-системе **Astryx**, API-клиент генерируется из OpenAPI через **Orval**.
Структура кода — Feature-Sliced Design. Подробности: [ARCHITECTURE.md](./ARCHITECTURE.md).

## Обязательное чтение перед задачей

| Тема | Файл |
| --- | --- |
| UI, компоненты, стили, токены | `AGENTS.md` (блок ASTRYX) — **правила жёсткие, не обходить** |
| Слои, границы импортов, поток данных | `ARCHITECTURE.md` |
| Генерация API-клиента, env, Docker | `orval.md` |
| Роутинг, loader/action, типы `+types` | `.agents/skills/react-router/SKILL.md` |

## Команды

```bash
yarn dev         # react-router dev (без регенерации API)
yarn local       # orval против dev-бэкенда + dev-сервер
yarn prod        # orval против prod-бэкенда + dev-сервер в mode=production
yarn orval       # только регенерация клиента
yarn build       # production-сборка
yarn typecheck   # react-router typegen && tsc
yarn test        # vitest run
yarn astryx <cmd>  # CLI дизайн-системы (см. AGENTS.md)
```

Линтера и форматтера нет. **После правок всегда прогоняй `yarn typecheck` и `yarn test`** — это
весь автоматический контроль. Не добавляй ESLint/Prettier без запроса.

Тесты (vitest + jsdom) покрывают две рискованные части: привязку маркеров к DOM
(`features/document-viewer/lib`) и разбор контракта движка (`entity/pii/model`). Остальное
проверяется только типами.

`src/shared/api/generated` импортируется кодом и лежит в репозитории вместе со снимком
схемы `src/shared/api/schemas/core.json`. `yarn orval` без переменной `ORVAL_BACKEND_ENV`
генерирует клиент из этого снимка — живой бэкенд для `yarn typecheck`/`yarn test` не нужен.
Снимок обновляется из FastAPI-приложения (`app.openapi()`), когда меняются эндпоинты.

## Правила работы с кодом

- **Никаких `<div>` и произвольных стилей в UI.** Только компоненты Astryx и token-backed
  Tailwind-утилиты. Перед написанием экрана — `astryx build "<идея>"`, затем
  `astryx component <Name>`. Полный свод — в `AGENTS.md`.
- **Не редактируй содержимое `src/shared/api/generated/`** — файлы перезаписываются Orval.
  Нужна доработка транспорта — правь `src/shared/api/mutators/authMutator.ts`.
- **Соблюдай направление импортов FSD**: `app → pages → features → entity → shared`.
  Импорт «вверх» или вбок внутри слоя — ошибка. Таблица в `ARCHITECTURE.md`.
- **Именование файлов — kebab-case** (`home-page.tsx`, `public-header.tsx`),
  экспортируемые компоненты — PascalCase.
- Роут-модули в `src/app/routes/**` держи тонкими: `meta`, `loader`/`action` и рендер
  страницы из `src/pages/**`. Логику в роут-модуль не переносить.
- Язык интерфейса — русский (`<html lang="ru">`). Тексты в UI пиши по-русски.

## Env

`.env` в гите нет, шаблон — `.env.example`:

```env
VITE_BACKEND_DEV_URL=http://localhost:8000
VITE_BACKEND_PROD_URL=https://42team.ru
```

Порт 8000 — тот же, что у `make api`, Dockerfile и docker-compose бэкенда. Пути запросов
включают префикс `/api`, поэтому в переменной он не нужен.

Выбор окружения для Orval — отдельная переменная `ORVAL_BACKEND_ENV=dev|prod`
(флаг `--mode` в Orval не попадает, см. `orval.md`). Без неё Orval берёт схему из
закоммиченного снимка `src/shared/api/schemas/core.json`.

## Известные расхождения

Это не «баги под фикс», а контекст. Не чини молча — сначала спроси.

1. **Фикстуры остались только в тестах.** `entity/pii/model/report.fixture.json` и
   `questions.fixture.json` — дословные артефакты прогона `masker.cli`; на них проверяются
   парсеры контракта (`schema.test.ts`, `answers.test.ts`, `review-store.test.ts`,
   `review-edits.test.ts`). Экраны берут данные у API: `features/masking-run/api/
   masking-run.ts` (прогон, вопросы, правки, артефакты, журнал) и
   `features/pii-review/api/use-review-data.ts` (единая точка входа `/review` и `/report`).

2. **Правки оператора применяет граф, а не клиент.** Кнопка «Утвердить документ» шлёт
   `POST /api/runs/{id}/review`; конверт собирает `entity/pii/model/review-edits.ts`.
   Никакой фильтрации критичных типов на клиенте нет и быть не должно — это `critical_guard`
   на бэкенде, второе место для той же защиты сделало бы её недоказуемой.

3. **Orval input.** `orval.config.ts` берёт схему с `${baseUrl}/openapi.json`, а `orval.md`
   описывает `/v3/api-docs`. FastAPI отдаёт первое; `orval.md` — наследие Java-бэкенда.

4. **XLSX.** Во фронте остались xlsx-вьюер и xlsx-фикстуры, а движок этот формат не
   обрабатывает вообще (`extract_node` принимает только `.docx` и `.pdf`), и API заводить
   прогон по нему отказывается (422). Из дропзоны xlsx поэтому убран; вьюер оставлен
   намеренно — решение владельца продукта.

5. **Экраны без данных.** `features/document-processing` (прогресс агентов, трейс вызовов,
   LLM-провайдеры) показывает фикстуры: под ним нет ни узла графа, ни таблицы в БД.
   Кнопки экспорта отчёта (CSV/XLSX/PDF) обработчиков не имеют — тоже намеренно.
   `/history` и скачивание документов работают через API.

<!-- ASTRYX:START -->
Astryx v0.5.2 · 163 components
CLI: run every command as `yarn astryx <cmd>` (shown below as `astryx ...`).

SETUP (once, in your app entry e.g. main.tsx) — without these, components render unstyled:
  import "@astryxdesign/core/reset.css";
  import "@astryxdesign/core/astryx.css";

WORKFLOW — discover, don't guess. Before writing UI:
1. `astryx build "<idea>"` — START HERE: returns a kit (closest [page] + [block]s + [component]s). No args = full playbook.
2. `astryx template <name> [--skeleton]` — scaffold the [page]/[block]s it named, or study their layout. Templates are reference code.
3. `astryx component <Name>` — props + examples for every component you use.

RULES:
- No <div> — components do all layout/spacing, page frame included.
- Frame first: read `astryx docs layout` before writing any page or screen — page frame, region widths, breakpoint behavior.
- Dense data = rows (Table, List/Item), never Card-wrapped list items; Card is for standalone widgets. Status = StatusDot/Token; Badge = counts only.
- Custom styling: component props first; else Tailwind utilities backed by tokens (bg-surface, text-primary, rounded-lg) via tailwind-theme.css. No raw hex/px.
- Tokens for every value (`astryx docs tokens`). Brand/accent belongs in the theme (`astryx theme list` / `theme add <slug>`, or `astryx theme template` for a custom one) — never override --color-* in :root.
- SELF-CHECK before you finish: re-read the file and replace any style={{…}}, raw <div>/<span> layout, imported .css/@apply, or hardcoded/arbitrary value (e.g. bg-[#fff], p-[13px]) with the component or a token-backed utility. If unsure a component/prop exists, run `astryx component <Name>` / `astryx search "<thing>"`; don't hand-roll CSS.

MORE CLI:
  search "<query>"   find any component / hook / doc / template / block
  component --list   163 components by category
  template --list    page + block recipes
  docs <topic>       browser-support, cli-integrations, color, elevation, getting-started, icons, illustrations, internationalization, layout, migration, motion, principles, shape, spacing, styling-libraries, styling, theme, tokens, typography, working-with-ai
  swizzle <Name>     eject component source for deep customization
  upgrade --apply    run after any @astryxdesign/core bump
<!-- ASTRYX:END -->
