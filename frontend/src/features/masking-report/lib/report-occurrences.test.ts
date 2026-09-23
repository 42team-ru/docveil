import { describe, expect, it } from "vitest";

import { maskingReportFixture } from "../../../entity/pii/model/fixtures";
import { flattenPiiOccurrences } from "../../../entity/pii/model/flatten";
import { maskedOccurrences } from "./report-occurrences";

describe("maskedOccurrences", () => {
  it("исключает находки, которые итоговый отчёт оставил без маскирования", () => {
    const firstRef = maskingReportFixture.decisions?.byRef[0]?.ref;
    expect(firstRef).toBeDefined();
    if (!firstRef || !maskingReportFixture.decisions) return;

    const report = {
      ...maskingReportFixture,
      decisions: {
        ...maskingReportFixture.decisions,
        byRef: maskingReportFixture.decisions.byRef.map((decision, index) =>
          index === 0 ? { ...decision, action: "keep" as const } : decision,
        ),
      },
    };

    const masked = maskedOccurrences(report);
    const removedCount = flattenPiiOccurrences(maskingReportFixture.extraction)
      .filter((occurrence) => occurrence.ref === firstRef).length;
    expect(masked.some((occurrence) => occurrence.ref === firstRef)).toBe(false);
    expect(masked.length).toBe(maskedOccurrences(maskingReportFixture).length - removedCount);
  });

  it("сохраняет уровень уверенности в плоских вхождениях", () => {
    const firstMasked = maskedOccurrences(maskingReportFixture)[0];
    expect(firstMasked).toBeDefined();
    if (!firstMasked) return;

    const sourceOccurrence = flattenPiiOccurrences(maskingReportFixture.extraction)
      .find((occurrence) => occurrence.id === firstMasked.id);

    expect(sourceOccurrence).toBeDefined();
    expect(firstMasked.level).toBe(sourceOccurrence?.level);
  });
});
