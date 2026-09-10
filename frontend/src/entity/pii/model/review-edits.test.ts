import { describe, expect, it } from "vitest";

import { maskingReportFixture } from "./fixtures";
import { flattenPiiOccurrences } from "./flatten";
import { buildReviewEdits } from "./review-edits";
import type { ManualPiiOccurrence, PiiDecisionKind, PiiType } from "./types";

const extraction = maskingReportFixture.extraction;
const occurrences = flattenPiiOccurrences(extraction);
const first = occurrences[0];

function state(overrides: {
  groupDecisions?: Record<string, PiiDecisionKind>;
  typeOverrides?: Record<string, PiiType>;
  occurrenceTypeOverrides?: Record<string, PiiType>;
  manualOccurrences?: ManualPiiOccurrence[];
}) {
  return {
    groupDecisions: {},
    typeOverrides: {},
    occurrenceTypeOverrides: {},
    manualOccurrences: [],
    ...overrides,
  };
}

describe("buildReviewEdits", () => {
  it("не отправляет решение по группе, которую оператор не трогал", () => {
    // Молчание значит «решение движка в силе»: отправить `mask` за
    // оператора — приписать ему согласие, которого он не давал.
    expect(buildReviewEdits(extraction, state({})).decisions).toEqual({});
  });

  it("разворачивает решение по группе в решения по всем её ссылкам", () => {
    const edits = buildReviewEdits(
      extraction,
      state({ groupDecisions: { [first.groupId]: "rejected" } }),
    );

    const refsOfGroup = occurrences
      .filter((item) => item.groupId === first.groupId)
      .map((item) => item.ref);

    expect(Object.keys(edits.decisions).sort()).toEqual([...refsOfGroup].sort());
    expect(new Set(Object.values(edits.decisions))).toEqual(new Set(["keep"]));
  });

  it("подтверждение группы уходит как явное «маскировать»", () => {
    const edits = buildReviewEdits(
      extraction,
      state({ groupDecisions: { [first.groupId]: "confirmed" } }),
    );

    expect(edits.decisions[first.ref]).toBe("mask");
  });

  it("адресный тип сильнее группового", () => {
    // Тот же порядок, что и DECISION_PRECEDENCE на бэкенде: персональное
    // решение по сущности сильнее решения по её группе.
    const edits = buildReviewEdits(
      extraction,
      state({
        typeOverrides: { [first.groupId]: "org_name" },
        occurrenceTypeOverrides: { [first.id]: "person" },
      }),
    );

    expect(edits.type_overrides[first.ref]).toBe("person");
  });

  it("добавленные вручную значения уходят типом и текстом", () => {
    const edits = buildReviewEdits(
      extraction,
      state({
        manualOccurrences: [
          {
            id: "manual-1",
            type: "phone",
            text: "+7 900 000-00-00",
            anchor: { format: "docx", label: "абзац 1", locator: ["body", 1] },
          },
        ],
      }),
    );

    expect(edits.manual).toEqual([{ type: "phone", text: "+7 900 000-00-00" }]);
  });
});
