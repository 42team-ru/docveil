import { beforeEach, describe, expect, it } from "vitest";

import { maskingReportFixture } from "./fixtures";
import { flattenPiiOccurrences, groupOccurrences } from "./flatten";
import { type ReviewGroup, useReviewStore } from "./review-store";
import { confirmedGroupCount } from "./selectors";

/** Группы документа в том виде, в каком их кладёт экран проверки. */
function groupsOf(report = maskingReportFixture): ReviewGroup[] {
  const grouped = groupOccurrences(flattenPiiOccurrences(report.extraction));
  return [...grouped.entries()].map(([id, occurrences]) => ({
    id,
    minConfidence: Math.min(...occurrences.map((o) => o.confidence)),
    appliedDecision: "confirmed" as const,
  }));
}

const initial = useReviewStore.getState();

beforeEach(() => {
  useReviewStore.setState({
    documentGroups: [],
    documentKey: null,
    groupDecisions: {},
    appliedGroupDecisions: {},
    occurrenceDecisions: {},
    appliedOccurrenceDecisions: {},
    typeOverrides: {},
    occurrenceTypeOverrides: {},
    selectedOccurrenceId: null,
    manualOccurrences: [],
    questionAnswers: {},
    viewMode: "all",
  });
});

describe("setDocumentGroups", () => {
  it("принимает группы открытого документа", () => {
    initial.setDocumentGroups("run-1:0", groupsOf());

    const state = useReviewStore.getState();
    expect(state.documentGroups).toHaveLength(8);
    expect(state.documentGroups.map((g) => g.id)).toContain("G1");
  });

  it("тот же документ не стирает решения оператора", () => {
    const groups = groupsOf();
    initial.setDocumentGroups("run-1:0", groups);
    initial.confirmGroup("G1");

    // Повторный рендер экрана отдаёт новый массив с тем же составом.
    initial.setDocumentGroups("run-1:0", groups.map((group) => ({ ...group })));

    expect(useReviewStore.getState().groupDecisions.G1).toBeUndefined();
    expect(useReviewStore.getState().appliedGroupDecisions.G1).toBe("confirmed");
  });

  it("другой документ сбрасывает решения", () => {
    initial.setDocumentGroups("run-1:0", groupsOf());
    initial.confirmGroup("G1");
    initial.answerQuestion("TYPE-phone", "оставить");

    initial.setDocumentGroups("run-2:0", [{ id: "X1", minConfidence: 1, appliedDecision: "confirmed" }]);

    const state = useReviewStore.getState();
    expect(state.groupDecisions).toEqual({});
    expect(state.questionAnswers).toEqual({});
    expect(state.documentGroups).toHaveLength(1);
  });
});

describe("черновик перегенерации", () => {
  it("снимает черновик, когда решение возвращается к опубликованному", () => {
    initial.setDocumentGroups("run-1:0", groupsOf());

    initial.rejectGroup("G1");
    expect(initial.hasUnappliedChanges()).toBe(true);

    initial.confirmGroup("G1");
    expect(useReviewStore.getState().groupDecisions).toEqual({});
    expect(initial.hasUnappliedChanges()).toBe(false);
  });

  it("разрешает оставить исходный текст только в одном вхождении", () => {
    const [occurrence] = flattenPiiOccurrences(maskingReportFixture.extraction);
    initial.setDocumentGroups("run-1:0", groupsOf());

    initial.rejectOccurrence(occurrence.id, occurrence.groupId);
    expect(useReviewStore.getState().occurrenceDecisions[occurrence.id]).toBe("rejected");
    expect(initial.hasUnappliedChanges()).toBe(true);

    initial.confirmOccurrence(occurrence.id, occurrence.groupId);
    expect(useReviewStore.getState().occurrenceDecisions[occurrence.id]).toBeUndefined();
    expect(initial.hasUnappliedChanges()).toBe(false);
  });

  it("сохраняет применённое исключение после перезагрузки версии", () => {
    const groups = groupsOf();
    groups[0] = { ...groups[0], appliedDecision: "rejected" as "confirmed" | "rejected" };
    initial.setDocumentGroups("run-1:1", groups);

    expect(useReviewStore.getState().appliedGroupDecisions.G1).toBe("rejected");
    initial.confirmGroup("G1");
    expect(initial.hasUnappliedChanges()).toBe(true);
  });
});

describe("confirmedGroupCount", () => {
  it("считает все группы подтверждёнными на только что открытом документе без кликов оператора", () => {
    const groups = groupsOf();
    initial.setDocumentGroups("run-1:0", groups);

    // Регрессия: раньше счёт брали из groupDecisions (клики этой сессии),
    // который пуст до первого клика, — бейдж показывал «0/N подтверждено»
    // на уже полностью замаскированном документе.
    expect(confirmedGroupCount(useReviewStore.getState())).toBe(groups.length);
  });

  it("не считает группу, применённое решение которой — «оставить как есть»", () => {
    const groups = groupsOf();
    groups[0] = { ...groups[0], appliedDecision: "rejected" as "confirmed" | "rejected" };
    initial.setDocumentGroups("run-1:0", groups);

    expect(confirmedGroupCount(useReviewStore.getState())).toBe(groups.length - 1);
  });

  it("следует за черновиком оператора, а не только за применённым решением", () => {
    const groups = groupsOf();
    initial.setDocumentGroups("run-1:0", groups);

    initial.rejectGroup("G1");
    expect(confirmedGroupCount(useReviewStore.getState())).toBe(groups.length - 1);

    initial.confirmGroup("G1");
    expect(confirmedGroupCount(useReviewStore.getState())).toBe(groups.length);
  });
});

describe("ручные отметки", () => {
  it("добавляются и удаляются", () => {
    const occurrence = {
      id: "manual-1",
      type: "person" as const,
      text: "Петров П.П.",
      anchor: maskingReportFixture.extraction.chunks[0].anchor,
    };

    initial.addManual(occurrence);
    expect(useReviewStore.getState().manualOccurrences).toHaveLength(1);

    initial.removeManual("manual-1");
    expect(useReviewStore.getState().manualOccurrences).toEqual([]);
  });
});
