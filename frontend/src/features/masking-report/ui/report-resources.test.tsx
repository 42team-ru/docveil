import { act, cloneElement, type ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { maskingReportFixture } from "../../../entity/pii/model/fixtures";
import type { MaskingReport, Telemetry } from "../../../entity/pii/model/types";
import type { RuntimeMetrics } from "../../masking-run/api/masking-run";

// jsdom не измеряет layout: у контейнера всегда нулевой размер, и
// `ResponsiveContainer` из recharts, ожидая ResizeObserver, ничего не
// рисует. Подменяем его на фиксированный размер — так дочерний график
// реально попадает в DOM и его можно проверить текстом, как остальную вёрстку.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: (
      { children, height }: { children: ReactElement<{ width?: number; height?: number }>; height?: number },
    ) => cloneElement(children, { width: 400, height: typeof height === "number" ? height : 240 }),
  };
});

const { ReportResources } = await import("./report-resources");

// jsdom не реализует matchMedia (https://github.com/jsdom/jsdom/issues/3522),
// а `useTheme` из Astryx опирается на него, чтобы отличать светлый/тёмный
// режим. Тестовому DOM он не нужен — режим стабильно "no match".
if (typeof window.matchMedia !== "function") {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as MediaQueryList;
}

const host = document.createElement("main");
document.body.append(host);
let root: Root = createRoot(host);
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
});

function withTelemetry(telemetry: Telemetry | null): MaskingReport {
  return { ...maskingReportFixture, telemetry };
}

const baseLlm = {
  calls: 3,
  promptTokens: 1200,
  completionTokens: 400,
  status: "charged",
  message: "Потрачено 1.329179 RUB.",
  cost: { amount: "1.329179", currency: "RUB" },
  byNode: [
    { node: "judge", calls: 2, promptTokens: 1000, completionTokens: 300 },
    { node: "summary", calls: 1, promptTokens: 200, completionTokens: 100 },
  ],
};

const eventsInOrder: Telemetry["events"] = [
  { sequence: 1, node: "extract", message: "разобран DOCX, 3 страницы" },
  { sequence: 2, node: "detect", message: "найдено 8 сущностей" },
  { sequence: 3, node: "profile", message: "профили сторон построены" },
  { sequence: 4, node: "judge", message: "проверка находок завершена" },
];

describe("ReportResources", () => {
  it("показывает пустое состояние без телеметрии", async () => {
    await act(async () =>
      root.render(<ReportResources report={withTelemetry(null)} runtime={null} />),
    );
    expect(host.textContent).toContain("Метрики недоступны");
  });

  it("строит конвейер по порядку прохождения графа, а не по алфавиту, и сворачивает шум", async () => {
    const runtime: RuntimeMetrics = {
      stages: {
        // Алфавитный порядок специально спутан с реальным ходом графа.
        apply_answers: { calls: 1, duration_ms: 1 },
        detect: { calls: 1, duration_ms: 42200 },
        extract: { calls: 1, duration_ms: 500 },
        judge: { calls: 1, duration_ms: 0 },
        profile: { calls: 1, duration_ms: 0 },
      },
    };
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: true, note: "" },
    });

    await act(async () => root.render(<ReportResources report={report} runtime={runtime} />));

    const text = host.textContent ?? "";
    // КПИ-плитка «Дольше всего» тоже упоминает «Поиск данных» — сравниваем
    // порядок только внутри самого графа конвейера, а не по всей странице.
    const pipelineStart = text.indexOf("По узлам графа");
    expect(pipelineStart).toBeGreaterThanOrEqual(0);
    // «Журнал обработки» ниже честно перечисляет все события, включая
    // свёрнутые в конвейере, — берём только область до него.
    const pipelineEnd = text.indexOf("Журнал обработки");
    const pipelineText = text.slice(pipelineStart, pipelineEnd);
    const extractIndex = pipelineText.indexOf("Извлечение");
    const detectIndex = pipelineText.indexOf("Поиск данных");
    expect(extractIndex).toBeGreaterThanOrEqual(0);
    expect(detectIndex).toBeGreaterThan(extractIndex);
    // Нулевые и почти нулевые стадии свёрнуты, а не выведены отдельными строками.
    expect(pipelineText).toContain("ещё 3 стадий, меньше 5 мс");
    expect(pipelineText).not.toContain("Проверка находок");
    // Самая долгая стадия видна в сводке.
    expect(text).toContain("Поиск данных");
    expect(text).toContain("42.2 с");
  });

  it("раскрывает свёрнутые стадии по клику", async () => {
    const runtime: RuntimeMetrics = {
      stages: {
        extract: { calls: 1, duration_ms: 500 },
        judge: { calls: 1, duration_ms: 0 },
      },
    };
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: true, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={runtime} />));
    // «Журнал обработки» ниже честно перечисляет все события со своими
    // узлами независимо от того, свёрнута ли стадия в конвейере, — область
    // проверки та же, что и в тесте выше: только сам блок конвейера.
    const textBefore = host.textContent ?? "";
    const pipelineTextBefore = textBefore.slice(
      textBefore.indexOf("По узлам графа"),
      textBefore.indexOf("Журнал обработки"),
    );
    expect(pipelineTextBefore).not.toContain("Проверка находок");
    const button = [...host.querySelectorAll("button")].find((el) =>
      el.textContent?.includes("Показать ещё"),
    );
    await act(async () => button?.click());
    const textAfter = host.textContent ?? "";
    const pipelineTextAfter = textAfter.slice(
      textAfter.indexOf("По узлам графа"),
      textAfter.indexOf("Журнал обработки"),
    );
    expect(pipelineTextAfter).toContain("Проверка находок");
  });

  it("округляет и локализует деньги: два знака после запятой и символ рубля", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: baseLlm,
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    expect(host.textContent).toContain("1,33 ₽");
    expect(host.textContent).not.toContain("1.329179");
  });

  it("показывает круговую по узлам в рублях, когда тариф задан", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: baseLlm,
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    expect(host.textContent).toContain("Стоимость по узлам");
    expect(host.textContent).toContain("Проверка находок");
    expect(host.textContent).toContain("Содержание");
  });

  it("без тарифа показывает токены, но не придумывает деньги", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, cost: null, message: "Токены не тарифицированы." },
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    expect(host.textContent).toContain("тариф не задан");
    expect(host.textContent).toContain("Токены по узлам");
    expect(host.textContent).not.toContain("₽");
  });

  it("показывает заглушку, когда модель не понадобилась", async () => {
    const report = withTelemetry({
      events: [eventsInOrder[0]],
      llm: { calls: 0, promptTokens: 0, completionTokens: 0, status: "model_not_needed", message: "Модель не понадобилась для этого документа.", cost: null, byNode: [] },
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    expect(host.textContent).toContain("Модель не понадобилась");
    expect(host.textContent).not.toContain("Стоимость по узлам");
    expect(host.textContent).not.toContain("Токены по узлам");
  });

  it("без длительностей показывает ленту событий и причину из runtime.note", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: false, note: "Метрики времени не записаны." },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    expect(host.textContent).toContain("Детали выполнения");
    expect(host.textContent).toContain("разобран DOCX, 3 страницы");
    expect(host.textContent).toContain("Метрики времени не записаны.");
  });

  // Фикстура — настоящая выдача движка (`report.fixture.json`):
  // `summary.by_source = {ner: 2, rule: 6}`, `summary.by_level = {confirmed: 7, probable: 1}`,
  // `decisions.by_ref` — 5 решений судьи и 3 гвардии критичных типов.
  it("показывает, чем и с какой уверенностью нашли сущности — по summary.bySource/byLevel", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    const text = host.textContent ?? "";
    expect(text).toContain("Чем нашли");
    expect(text).toContain("Правила");
    expect(text).toContain("Локальный NER (Natasha)");
    // В фикстуре нет находок модели (`by_source` без ключа `llm`) — 100%.
    expect(text).toContain("100% сущностей нашли правила и локальный NER без обращения к модели.");
    expect(text).toContain("С какой уверенностью");
    expect(text).toContain("Подтверждено");
    expect(text).toContain("Вероятно");
    // «Похоже» (possible) в фикстуре нулевое — пустая категория не рисуется.
    expect(text).not.toContain("Похоже");
  });

  it("показывает, кем принято решение — по decisions.byRef, без выдуманных категорий", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    const text = host.textContent ?? "";
    expect(text).toContain("Кем принято решение");
    expect(text).toContain("судья");
    expect(text).toContain("гвардия");
  });

  it("честно признаёт, что детекцию нельзя разложить на правила/NER/GLiNER/LLM", async () => {
    const runtime: RuntimeMetrics = {
      stages: {
        extract: { calls: 1, duration_ms: 500 },
        detect: { calls: 1, duration_ms: 4200 },
        validate: { calls: 1, duration_ms: 100 },
      },
    };
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: true, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={runtime} />));
    const text = host.textContent ?? "";
    expect(text).toContain("Конвейер по слоям");
    expect(text).toContain("Поиск данных (правила + NER + GLiNER + LLM-арбитраж вместе)");
    expect(text).toContain("Проверка утечек");
    expect(text).toContain(
      "Разбивку по этим слоям должен дать бэкенд отдельной задачей — сейчас таких данных в телеметрии нет.",
    );
  });

  it("журнал обработки показывает время от старта, когда есть runtime.events", async () => {
    // Используем ненулевые секунды — formatElapsed округляет до секунд, значения
    // < 1000 мс дали бы одинаковый "+0:00:00" и не подтвердили бы, что время передано.
    const runtime: RuntimeMetrics = {
      stages: { extract: { calls: 1, duration_ms: 500 } },
      events: [
        { sequence: 1, elapsed_ms: 5_000, node: "extract", message: "разобран DOCX, 3 страницы" },
        { sequence: 2, elapsed_ms: 62_000, node: "detect", message: "найдено 8 сущностей" },
      ],
    };
    const report = withTelemetry({
      events: eventsInOrder.slice(0, 2),
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: true, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={runtime} />));
    const text = host.textContent ?? "";
    const logStart = text.indexOf("Детали выполнения");
    expect(logStart).toBeGreaterThanOrEqual(0);
    const logText = text.slice(logStart);
    expect(logText).toContain("разобран DOCX, 3 страницы");
    // formatElapsed(5000) → "+0:00:05"; formatElapsed(62000) → "+0:01:02"
    expect(logText).toContain("+0:00:05");
    expect(logText).toContain("найдено 8 сущностей");
    expect(logText).toContain("+0:01:02");
  });

  it("журнал обработки без runtime показывает события без времени, а не выдумывает его", async () => {
    const report = withTelemetry({
      events: eventsInOrder,
      llm: { ...baseLlm, calls: 0, cost: null, byNode: [] },
      runtime: { available: false, note: "" },
    });
    await act(async () => root.render(<ReportResources report={report} runtime={null} />));
    const text = host.textContent ?? "";
    const logStart = text.indexOf("Детали выполнения");
    expect(logStart).toBeGreaterThanOrEqual(0);
    const logText = text.slice(logStart);
    expect(logText).toContain("разобран DOCX, 3 страницы");
    expect(logText).toContain("Время каждого шага недоступно");
  });
});
