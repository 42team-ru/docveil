FROM node:22-alpine AS deps

WORKDIR /app

COPY package.json yarn.lock ./
RUN yarn install --frozen-lockfile


FROM node:22-alpine AS build

WORKDIR /app

COPY . .
COPY --from=deps /app/node_modules ./node_modules

# Адреса бэкенда — необязательные аргументы сборки: без них приложение берёт
# значения по умолчанию из `authMutator.ts`, а образ всё равно собирается.
ARG VITE_BACKEND_DEV_URL
ARG VITE_BACKEND_PROD_URL

# Пусто по умолчанию, а НЕ `prod`. При `prod` orval.config.ts идёт за схемой к
# живому бэкенду и падает, если адрес не передали, — именно на этом свалился
# первый релиз (workflow «Tests» #76, 10.09.2026). Релизный образ обязан
# собираться из одного репозитория: иначе прошлый релиз нельзя пересобрать, а
# сборка зависит от того, поднят ли сейчас чужой сервер. Без этой переменной
# orval берёт закоммиченный снимок схемы `core.json`.
ARG ORVAL_BACKEND_ENV=

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