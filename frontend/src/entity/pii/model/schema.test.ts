import { describe, expect, it } from "vitest";

import { askEnvelopeFixture, maskingReportFixture } from "./fixtures";
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
