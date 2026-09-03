import { defineConfig } from "vitest/config";

/**
 * Тесты только для features/document-viewer/lib — самой рискованной части
 * фичи просмотра ПДн (привязка маркеров к DOM). Остальной проект по-прежнему
 * проверяется только `yarn typecheck`, см. CLAUDE.md.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
  },
});
