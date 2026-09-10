import { defineConfig } from "vitest/config";

/**
 * Тесты покрывают две самые рискованные части: привязку маркеров к DOM
 * (`features/document-viewer/lib`) и разбор контракта движка
 * (`entity/pii/model` — `report.json` и конверт ответов). Остальной проект
 * по-прежнему проверяется только `yarn typecheck`, см. CLAUDE.md.
 *
 * `.tsx` в маске тоже: без него тест рядом с компонентом молча не запускался
 * бы — хуже, чем его отсутствие.
 */
export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
