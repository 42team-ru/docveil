import { defineConfig } from "orval";
import { loadEnv } from "vite";

const env = loadEnv(process.env.NODE_ENV ?? "development", process.cwd(), "");

const backendEnv = process.env.ORVAL_BACKEND_ENV ?? "dev";

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

export default defineConfig({
  core: {
    // input: "./src/shared/api/schemas/core.json",
    input: `${baseUrl}/openapi.json`,
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
