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

Фронт работает через HTTP API бэкенда (`backend/src/api`). Прогон обезличивания — это
`POST /api/runs`: запрос ставит задачу и сразу отдаёт `run_id`, а граф LangGraph крутится
на сервере. Фронт **опрашивает** `GET /api/runs/{id}` (react-query `refetchInterval`) —
ни WebSocket, ни SSE тут нет: опрос переживает обрыв связи и перезагрузку вкладки, потому
что читает состояние из чекпойнтера графа, а не из соединения.

У прогона два прерывания, и это разные состояния экрана:

| Статус | Что это | Что делает фронт |
|---|---|---|
| `queued` / `running` | граф идёт | опрашивает состояние |
| `awaiting_answers` | пауза `ask_human` | `GET …/questions`, ответы → `POST …/answers` |
| `awaiting_review` | отчёт готов, ждём оператора | показывает документ и отчёт, правки → `POST …/review` |
| `done` / `leaked` | прогон закончен | отчёт, скачивание артефактов |
| `failed` | узел графа упал | показывает причину из `error` |

Правки оператора (снять маску, сменить тип, добавить пропущенное значение) не применяются
на клиенте: они уходят вторым прерыванием в граф, и документ пересобирается там же —
поэтому согласованность маркеров, защита критичных типов и проверка утечек держатся тем же
кодом, что и на первом проходе.

Единая точка входа за данными экранов проверки и отчёта — `src/features/pii-review/api/
use-review-data.ts`; запросы к прогону — `src/features/masking-run/api/masking-run.ts`.
Ответы разбирают `parseMaskingReport`/`parseAskEnvelope` (`src/entity/pii/model/schema.ts`)
— тот же код, что раньше разбирал фикстуры: `report.fixture.json` и `questions.fixture.json`
остались как контрактные фикстуры тестов.

| | |
|---|---|
| API | `http://localhost:8000` (dev), `https://42team.ru` (prod) — пути включают `/api` |
| Аутентификация | JWT: access в памяти вкладки, refresh в httpOnly-cookie (`src/shared/api/auth-token.ts`) |
| Документы | загрузка `multipart/form-data`, хранение в MinIO; артефакты — `GET …/artifacts/{role}` |
| Клиент | генерируется Orval в `src/shared/api/generated` из `src/shared/api/schemas/core.json` |

Контракты эндпоинтов — `../backend/src/api/routers/`, коллекция Postman — `../postman/`.
Правила работы с кодом — `CLAUDE.md` и `AGENTS.md`, архитектура — `ARCHITECTURE.md`.
