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