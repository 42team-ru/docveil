import { defineConfig } from "orval";
import { loadEnv } from "vite";

const env = loadEnv(process.env.NODE_ENV ?? "development", process.cwd(), "");

// Схема берётся у живого бэкенда, когда явно указано окружение
// (`yarn local`/`yarn prod` выставляют ORVAL_BACKEND_ENV), и из
// закоммиченного снимка `core.json` — когда нет. Иначе `yarn orval` и
// `yarn typecheck` требуют поднятого бэкенда там, где хватает файла;
// снимок обновляется скриптом `scripts/dump-openapi` бэкенда.
const backendEnv = process.env.ORVAL_BACKEND_ENV;

const liveSchemaUrl = () => {
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

  return `${baseUrl}/openapi.json`;
};

export default defineConfig({
  core: {
    input: backendEnv ? liveSchemaUrl() : "./src/shared/api/schemas/core.json",
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
