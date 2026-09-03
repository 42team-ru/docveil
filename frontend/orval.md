# Orval + Frontend: заметка для Backend и DevOps

## Контекст

На фронте перед запуском dev-режима или production build нужно перегенерировать TypeScript API-клиент через **Orval**.

Orval берёт OpenAPI/Swagger схему из backend endpoint:

```text
/v3/api-docs
```

То есть итоговый URL выглядит так:

```text
{BACKEND_URL}/v3/api-docs
```

Например:

```text
http://localhost:8080/v3/api-docs
https://api.example.com/v3/api-docs
```

---

## Что нужно от Backend

Backend должен отдавать валидную OpenAPI/Swagger схему по адресу:

```text
/v3/api-docs
```

Для каждого окружения должен быть доступен свой backend URL:

```env
VITE_BACKEND_DEV_URL=http://localhost:8080
VITE_BACKEND_PROD_URL=https://api.example.com
```

Важно, чтобы endpoint был доступен на момент генерации Orval.

Если Orval не может получить или распарсить схему, сборка фронта падает с ошибкой вида:

```text
Failed to parse JSON/YAML from URL: .../v3/api-docs
Failed to resolve input
```

---

## Что нужно от DevOps

При Docker build нужно передать backend URL через build args.

Для production backend:

```bash
docker build \
  --build-arg ORVAL_BACKEND_ENV=prod \
  --build-arg VITE_BACKEND_PROD_URL=https://api.example.com \
  --build-arg VITE_BACKEND_DEV_URL=http://localhost:8080 \
  -t frontend-prod .
```

Для dev backend:

```bash
docker build \
  --build-arg ORVAL_BACKEND_ENV=dev \
  --build-arg VITE_BACKEND_DEV_URL=http://localhost:8080 \
  --build-arg VITE_BACKEND_PROD_URL=https://api.example.com \
  -t frontend-dev .
```

Главная переменная выбора окружения:

```env
ORVAL_BACKEND_ENV=dev
```

или:

```env
ORVAL_BACKEND_ENV=prod
```

---

## Dockerfile

Orval запускается на этапе build, до сборки фронта.

В финальном nginx-контейнере Orval не запускается, потому что там нет Node.js, yarn, исходников и node_modules.

```dockerfile
FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile


FROM node:22-alpine AS build

WORKDIR /app

COPY . .
COPY --from=deps /app/node_modules ./node_modules

ARG VITE_BACKEND_DEV_URL
ARG VITE_BACKEND_PROD_URL
ARG ORVAL_BACKEND_ENV=prod

ENV VITE_BACKEND_DEV_URL=${VITE_BACKEND_DEV_URL}
ENV VITE_BACKEND_PROD_URL=${VITE_BACKEND_PROD_URL}
ENV ORVAL_BACKEND_ENV=${ORVAL_BACKEND_ENV}

RUN yarn orval
RUN yarn build


FROM nginx:alpine

COPY --from=build /app/build/client /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

---

## Frontend scripts

Для локальной разработки используются команды:

```json
{
  "scripts": {
    "orval": "orval",
    "local": "cross-env ORVAL_BACKEND_ENV=dev orval && react-router dev",
    "prod": "cross-env ORVAL_BACKEND_ENV=prod orval && react-router dev --mode production",
    "build": "react-router build"
  }
}
```

`cross-env` нужен для корректной работы переменных окружения на Windows/macOS/Linux.

---

## Почему не хватает `--mode production`

Команда:

```bash
orval && react-router dev --mode production
```

не передаёт `--mode production` в Orval.

`--mode production` получает только `react-router dev`, потому что Orval запускается раньше.

Поэтому для Orval используется отдельная переменная:

```env
ORVAL_BACKEND_ENV=prod
```

---

## Orval config

```ts
import { defineConfig } from "orval";
import { loadEnv } from "vite";

const backendEnv = process.env.ORVAL_BACKEND_ENV ?? "dev";
const mode = backendEnv === "prod" ? "production" : "development";

const env = loadEnv(mode, process.cwd(), "");

const baseUrl =
  backendEnv === "prod"
    ? (process.env.VITE_BACKEND_PROD_URL ?? env.VITE_BACKEND_PROD_URL)
    : (process.env.VITE_BACKEND_DEV_URL ?? env.VITE_BACKEND_DEV_URL);

if (!baseUrl) {
  throw new Error(
    `Backend URL is required to run Orval. Missing ${
      backendEnv === "prod" ? "VITE_BACKEND_PROD_URL" : "VITE_BACKEND_DEV_URL"
    }.`,
  );
}

console.log(`[orval] backendEnv=${backendEnv}`);
console.log(`[orval] baseUrl=${baseUrl}`);

export default defineConfig({
  core: {
    input: `${baseUrl}/v3/api-docs`,
    output: {
      target: "./src/shared/api/generated/core",
      client: "react-query",
      mode: "tags-split",
      override: {
        mutator: {
          path: "./src/shared/api/mutators/authMutator.ts",
          name: "authMutator",
        },
      },
    },
  },
});
```

---

## Частые проблемы

### Orval всё равно идёт на localhost

Проверить:

1. Передаётся ли `ORVAL_BACKEND_ENV=prod`.
2. Передаётся ли `VITE_BACKEND_PROD_URL`.
3. Нет ли старой переменной `VITE_BACKEND_URL=http://localhost:8080`.
4. Нет ли старой логики в `orval.config.ts`, которая читает только `VITE_BACKEND_URL`.
5. Видны ли в логе строки:

```text
[orval] backendEnv=prod
[orval] baseUrl=https://api.example.com
```

### Ошибка `Failed to parse JSON/YAML from URL`

Проверить:

1. Доступен ли backend из контейнера/build environment.
2. Открывается ли `{BACKEND_URL}/v3/api-docs`.
3. Возвращается ли именно JSON/YAML OpenAPI schema, а не HTML, 404 или auth error.
4. Не нужен ли доступ через внутренний Docker network hostname вместо `localhost`.

Важно: внутри Docker `localhost` означает сам контейнер, а не хост-машину.

---

## Коротко

Backend:

- отдаёт OpenAPI schema по `/v3/api-docs`;
- обеспечивает доступность endpoint для dev/prod окружений.

DevOps:

- передаёт `ORVAL_BACKEND_ENV`;
- передаёт `VITE_BACKEND_DEV_URL` и `VITE_BACKEND_PROD_URL`;
- запускает Orval на этапе Docker build, до `yarn build`.

Frontend:

- генерирует API-клиент через Orval;
- использует разные backend URL в зависимости от `ORVAL_BACKEND_ENV`.
