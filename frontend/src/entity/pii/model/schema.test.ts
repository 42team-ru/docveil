import { describe, expect, it } from "vitest";

import type { ReportOut } from "../../../shared/api/generated/core/triemaMaskerAPI.schemas";
import { askEnvelopeFixture, maskingReportFixture } from "./fixtures";
import reportPayload from "./report.fixture.json";
import { parseMaskingReport } from "./schema";
import { KEEP_CRITICAL_OPTION, MASK_OPTION } from "./types";

/**
 * Тесты идут по настоящей выдаче движка (`report.fixture.json`,
 * `questions.fixture.json`), а не по собранному под парсер объекту: смысл
 * проверки в том, чтобы расхождение контракта падало здесь, а не у оператора.
 */
describe("parseMaskingReport", () => {
  it("разбирает отчёт целиком, не теряя секций", () => {
    expect(maskingReportFixture.reportVersion).toBe(3);
    expect(maskingReportFixture.input).toBe("contract_08_roles.docx");
    expect(maskingReportFixture.format).toBe("docx");
    expect(maskingReportFixture.entityCount).toBe(8);
    expect(maskingReportFixture.plan).not.toBeNull();
    expect(maskingReportFixture.contractSummary).not.toBeNull();
    expect(maskingReportFixture.decisions).not.toBeNull();
    expect(maskingReportFixture.validation).not.toBeNull();
    expect(maskingReportFixture.limitations.length).toBeGreaterThan(0);
  });

  it("сводка совпадает с числом разобранных вхождений", () => {
    const occurrences = maskingReportFixture.extraction.chunks.flatMap(
      (chunk) => chunk.pii,
    );

    expect(maskingReportFixture.summary.entitiesTotal).toBe(occurrences.length);
    expect(maskingReportFixture.summary.byType.inn).toBe(2);
    expect(maskingReportFixture.summary.bySource.rule).toBe(6);
    expect(maskingReportFixture.summary.minimumConfidence).toBe(0.75);
  });

  it("маркер группы несёт роль стороны, а не один лишь тип", () => {
    const groups = maskingReportFixture.plan?.groups ?? [];
    const markers = groups.map((group) => group.marker);

    expect(markers).toContain("[ЗАКАЗЧИК-ОРГАНИЗАЦИЯ]");
    expect(markers).toContain("[ИСПОЛНИТЕЛЬ-ИНН]");
    expect(groups.every((group) => group.profileId !== "")).toBe(true);
  });

  it("разбирает якорь и с ключом format, и с ключом fmt", () => {
    // `chunks[].anchor` приходит как `format`, `profile_judge` — как `fmt`.
    const chunkAnchor = maskingReportFixture.extraction.chunks[0].anchor;
    const memberAnchor = maskingReportFixture.profiles[0].members[0].anchor;

    expect(chunkAnchor.format).toBe("docx");
    expect(memberAnchor.format).toBe("docx");
    expect(memberAnchor.locator).toEqual(["body", 1]);
  });

  it("роли сторон открытые — берутся из формулировки документа", () => {
    const roles = maskingReportFixture.profiles.map((p) => p.roleTitle);
    expect(roles).toEqual(["Заказчик", "Исполнитель"]);

    const labels = maskingReportFixture.profiles.map((p) => p.markerLabel);
    expect(labels).toEqual(["ЗАКАЗЧИК", "ИСПОЛНИТЕЛЬ"]);
  });

  it("карточка договора собрана из профилей", () => {
    const summary = maskingReportFixture.contractSummary;

    expect(summary?.customer?.name).toBe("ООО «Северный свет»");
    expect(summary?.customer?.inn).toBe("3662103003");
    expect(summary?.supplier?.roleTitle).toBe("Исполнитель");
    expect(summary?.llmCalls).toBe(0);
  });

  it("решения движка читаются по ссылкам, а не из чанков", () => {
    const decisions = maskingReportFixture.decisions;
    const byRef = new Map(decisions?.byRef.map((d) => [d.ref, d]));

    expect(decisions?.mode).toBe("non_interactive");
    expect(byRef.get("E1")?.decidedBy).toBe("judge");
    // ИНН критичен: решение принимает гвардия, а не судья.
    expect(byRef.get("E2")?.decidedBy).toBe("critical_guard");
    expect(byRef.get("E2")?.action).toBe("mask");
    expect(decisions?.criticalUnmasked).toEqual([]);
  });

  it("видит типы, которые запрошены, но детектора не имеют", () => {
    expect(maskingReportFixture.detectionCoverage.requestedWithoutDetector).toEqual([
      "bank_name",
      "money",
    ]);
  });

  it("проверка утечек прошла", () => {
    expect(maskingReportFixture.validation?.ok).toBe(true);
    expect(maskingReportFixture.validation?.leakedCount).toBe(0);
  });

  it("сертификат обезличивания приходит и на верхнем уровне, и внутри validation", () => {
    expect(maskingReportFixture.certificate?.ok).toBe(true);
    expect(maskingReportFixture.certificate?.checks.map((c) => c.name)).toEqual([
      "leak_scan",
      "metadata_cleared",
      "width_quantization",
    ]);
    expect(maskingReportFixture.validation?.certificate).toEqual(
      maskingReportFixture.certificate,
    );
  });

  it("уровень уверенности (Р8) размечен по сущностям и по группам плана", () => {
    const phone = maskingReportFixture.extraction.chunks
      .flatMap((chunk) => chunk.pii)
      .find((pii) => pii.type === "phone");
    // Единственный сигнал без контрольной суммы — "probable", не "confirmed".
    expect(phone?.level).toBe("probable");

    expect(maskingReportFixture.summary.byLevel).toEqual({
      confirmed: 7,
      probable: 1,
    });

    const phoneGroup = maskingReportFixture.plan?.groups.find(
      (group) => group.type === "phone",
    );
    expect(phoneGroup?.level).toBe("probable");

    // Ни одной группы уровня "possible" в этом документе нет.
    expect(maskingReportFixture.reviewPossible).toEqual([]);
  });

  it("regions/pages пусты у docx-фикстуры без PDF-артефакта", () => {
    // report.fixture.json снят до плана feat/highlight-coords-edits — ключей
    // pages/regions в нём нет вовсе, а не пустые массивы. Парсер обязан
    // подставить [] сам, а не упасть на отсутствующем ключе.
    expect(maskingReportFixture.pages).toEqual([]);
    const occurrences = maskingReportFixture.extraction.chunks.flatMap(
      (chunk) => chunk.pii,
    );
    expect(occurrences.length).toBeGreaterThan(0);
    expect(occurrences.every((pii) => pii.regions.length === 0)).toBe(true);
  });

  it("разбирает pages и regions, когда бэкенд их прислал (план К1)", () => {
    const withRegions = structuredClone(reportPayload) as Record<string, unknown>;
    withRegions.pages = [{ page: 0, width_pt: 595, height_pt: 842 }];
    const chunks = withRegions.chunks as Array<{ pii: Array<Record<string, unknown>> }>;
    chunks[0].pii[0].regions = [{ page: 0, x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.25 }];

    const report = parseMaskingReport(withRegions as unknown as ReportOut);

    expect(report.pages).toEqual([{ page: 0, widthPt: 595, heightPt: 842 }]);
    const firstOccurrence = report.extraction.chunks[0].pii[0];
    expect(firstOccurrence.regions).toEqual([
      { page: 0, x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.25 },
    ]);
  });

  it("формат картинки не подменяется на docx (регресс toDocFormat)", () => {
    const asImage = structuredClone(reportPayload) as Record<string, unknown>;
    asImage.format = "jpg";

    const report = parseMaskingReport(asImage as unknown as ReportOut);

    expect(report.format).toBe("jpg");
  });

  it("null у plan/profile_judge/contract_summary/decisions не роняет разбор", () => {
    // Бэкенд шлёт `X | None = None` как JSON `null`, не опускает ключ —
    // для PDF `--profile` не строится вовсе (run_service._run_options),
    // и `report.json` реального PDF-прогона несёт ровно такие null.
    const withNulls = structuredClone(reportPayload) as Record<string, unknown>;
    withNulls.plan = null;
    withNulls.profile_judge = null;
    withNulls.contract_summary = null;
    withNulls.decisions = null;

    const report = parseMaskingReport(withNulls as unknown as ReportOut);

    expect(report.plan).toBeNull();
    expect(report.profiles).toEqual([]);
    expect(report.contractSummary).toBeNull();
    expect(report.decisions).toBeNull();
  });

  it("читает жанр, пересказ и телеметрию нового контракта отчёта", () => {
    const enriched = structuredClone(reportPayload) as Record<string, unknown>;
    enriched.contract_summary = {
      document_kind: { status: "non_contract", genre: "технические условия" },
      brief_summary: "Документ задаёт требования к поставке и контролю качества.",
    };
    enriched.telemetry = {
      events: [{ sequence: 1, node: "extract", message: "разобран DOCX, 3 страниц" }],
      llm: {
        calls: 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        status: "model_not_needed",
        message: "Модель не понадобилась для этого документа.",
        cost: null,
        by_node: [],
      },
      runtime: { available: false, note: "Метрики времени не записаны." },
    };

    const report = parseMaskingReport(enriched as unknown as ReportOut);

    expect(report.contractSummary?.documentKind).toEqual({
      status: "non_contract",
      genre: "технические условия",
    });
    expect(report.contractSummary?.briefSummary).toContain("требования");
    expect(report.telemetry?.events[0]?.message).toContain("DOCX");
    expect(report.telemetry?.llm.calls).toBe(0);
    expect(report.telemetry?.llm.byNode).toEqual([]);
  });
});

describe("parseAskEnvelope", () => {
  it("разбирает конверт паузы графа", () => {
    expect(askEnvelopeFixture.schemaVersion).toBe(1);
    expect(askEnvelopeFixture.threadId).toBe("a32c684475479812");
    expect(askEnvelopeFixture.questions).toHaveLength(7);
  });

  it("критичному типу движок не предлагает снять маску", () => {
    const inn = askEnvelopeFixture.questions.find((q) => q.id === "TYPE-inn");

    expect(inn?.critical).toBe(true);
    // Без флага прогона `--unmask-critical` вариант ровно один.
    expect(inn?.options).toEqual([MASK_OPTION]);
    expect(inn?.options).not.toContain(KEEP_CRITICAL_OPTION);
    expect(inn?.default).toBe(MASK_OPTION);
  });

  it("вопрос по профилю адресует сторону целиком", () => {
    const profile = askEnvelopeFixture.questions.find(
      (q) => q.id === "PROFILE-P1",
    );

    expect(profile?.kind).toBe("profile");
    expect(profile?.target).toBe("P1");
    expect(profile?.found).toBe(4);
    expect(profile?.anchors).toContain("абзац 5");
  });
});
