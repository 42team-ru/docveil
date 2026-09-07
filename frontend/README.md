# frontend

Веб-интерфейс обезличивателя: React Router v8 (framework mode) + React 19 + Vite 8,
UI на дизайн-системе Astryx, структура — Feature-Sliced Design.

## Экраны

| Путь | Что делает |
|---|---|
| `/` | загрузка документа, выбор типов данных и стиля маски |
| `/review` | проверка замен: документ с подсветкой слева, панель решений справа — замены, профили сторон, вопросы движка, карточка договора |
| `/report` | сводка прогона и перечень заменённых фрагментов |
| `/history` | журнал обработок |
| `/login` | вход |

## Запуск

```bash
yarn install
yarn dev         # dev-сервер
yarn typecheck   # react-router typegen && tsc
yarn test        # vitest run
```

Ни одна из этих команд не требует бэкенда.

## Связь с бэкендом

**Запросов к API фронт пока не делает**, и это не недоделка интерфейса: на бэкенде нет
HTTP-эндпоинтов маскирования вовсе. Наружу выведены только `auth`, `users`,
`files/upload` (кладёт файл в MinIO) и `custom_types/compile` — движок работает через CLI
(`docs/CLI.md`) и Python-API `masker.run`.

Поэтому экраны читают фикстуры — но фикстуры настоящие: `src/entity/pii/model/
report.fixture.json` и `questions.fixture.json` это дословные артефакты прогона
`masker.cli` по `backend/fixtures/labeled/contract_08_roles.docx`, а не собранные руками
объекты. Разбирает их `src/entity/pii/model/schema.ts` (`parseMaskingReport`,
`parseAskEnvelope`) — тот же код будет разбирать и ответ по HTTP.

Единая точка входа за данными экрана проверки — `src/features/pii-review/api/
use-review-data.ts`. Подключение к API должно свестись к замене её содержимого:
возвращаемый тип менять не придётся.

| | |
|---|---|
| API | `http://localhost:8080/api` (dev), `https://42team.ru/api` (prod) |
| Аутентификация | JWT, refresh-токен в httpOnly-cookie; транспорт готов в `src/shared/api/mutators/authMutator.ts`, но не подключён |
| Документы | загрузка `multipart/form-data`, хранение в MinIO |

Контракты эндпоинтов — `../backend/src/api/routers/`, коллекция Postman — `../postman/`.
Правила работы с кодом — `CLAUDE.md` и `AGENTS.md`, архитектура — `ARCHITECTURE.md`.
