import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { maskingReportFixture } from "../../entity/pii/model/fixtures";
import type { MaskingReport } from "../../entity/pii/model/types";

vi.mock("../../features/masking-report/ui/report-table", () => ({
  ReportTable: () => createElement("section", null, "Замены в документе"),
}));

const { ReportView } = await import("./report-view");
const host = document.createElement("main");
document.body.append(host);
let root: Root;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
});

describe("ReportView", () => {
  it("показывает результат, сводку затрат, замены и проверки", async () => {
    const report: MaskingReport = {
      ...maskingReportFixture,
      telemetry: {
        events: [],
        llm: {
          calls: 2,
          promptTokens: 100,
          completionTokens: 20,
          status: "charged",
          message: "",
          cost: { amount: "1.33", currency: "RUB" },
          pricing: null,
          byNode: [],
        },
        runtime: { available: false, note: "" },
      },
    };
    await act(async () =>
      root.render(<ReportView report={report} runId={null} status="done" canDownload />),
    );

    expect(host.textContent).toContain("Обезличивание завершено");
    expect(host.textContent).toContain("2 обращения к модели");
    expect(host.textContent).toContain("1,33 ₽");
    expect(host.textContent).toContain("120 токенов");
    expect(host.textContent).toContain("Замены в документе");
    expect(host.textContent).toContain("Проверки и ограничения");
    expect(host.textContent).toContain("Исходные данные не остались в файле");
    expect(host.textContent).not.toContain("Ресурсы и обработка");
    expect(host.textContent).not.toContain("Подробности обработки");
    expect(host.textContent).not.toContain("Стоимость модели");
    expect(host.querySelector("button[aria-expanded]")).toBeNull();
  });

  it("при утечке показывает проблему и подробность непройденной проверки", async () => {
    const report: MaskingReport = {
      ...maskingReportFixture,
      certificate: {
        ok: false,
        checks: [
          { name: "leak_scan", ok: false, detail: "Найдена исходная строка" },
          {
            name: "width_quantization",
            ok: false,
            detail: "E120: ширина маски не кратна шагу",
          },
        ],
      },
    };
    await act(async () =>
      root.render(<ReportView report={report} runId={null} status="leaked" />),
    );

    expect(host.textContent).toContain("Проверка результата не пройдена");
    expect(host.textContent).toContain("Не пройдено · Исходные данные не остались в файле");
    expect(host.textContent).toContain("Найдена исходная строка");
    expect(host.textContent).not.toContain("Маски PDF проверены");
    expect(host.textContent).not.toContain("E120");
  });

  it("читает проверки из validation, когда отдельного сертификата нет", async () => {
    const report: MaskingReport = { ...maskingReportFixture, certificate: null };
    await act(async () =>
      root.render(<ReportView report={report} runId={null} status="done" />),
    );

    expect(host.textContent).toContain("Основные проверки результата пройдены");
    expect(host.textContent).toContain("Личные данные удалены из метаданных");
    expect(host.textContent).not.toContain("Показать все проверки");
  });
});
