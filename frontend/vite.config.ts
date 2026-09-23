import { reactRouter } from "@react-router/dev/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [tailwindcss(), reactRouter()],
    resolve: {
      tsconfigPaths: true,
    },
    server: {
      proxy: {
        "/api": {
          target: env.VITE_BACKEND_DEV_URL || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
  };
});
