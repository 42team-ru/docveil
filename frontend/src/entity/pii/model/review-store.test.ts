import { beforeEach, describe, expect, it } from "vitest";

import { maskingReportFixture } from "./fixtures";
import { flattenPiiOccurrences, groupOccurrences } from "./flatten";
import { useReviewStore } from "./review-store";

/** Группы документа в том виде, в каком их кладёт экран проверки. */
function groupsOf(report = maskingReportFixture) {
  const grouped = groupOccurrences(flattenPiiOccurrences(report.extraction));
  return [...grouped.entries()].map(([id, occurrences]) => ({
    id,
    minConfidence: Math.min(...occurrences.map((o) => o.confidence)),
  }));
}

const initial = useReviewStore.getState();

beforeEach(() => {
  useReviewStore.setState({
    documentGroups: [],
    groupDecisions: {},
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
    initial.setDocumentGroups(groupsOf());

    const state = useReviewStore.getState();
    expect(state.documentGroups).toHaveLength(8);
    expect(state.documentGroups.map((g) => g.id)).toContain("G1");
  });

  it("тот же документ не стирает решения оператора", () => {
    const groups = groupsOf();
    initial.setDocumentGroups(groups);
    initial.confirmGroup("G1");

    // Повторный рендер экрана отдаёт новый массив с тем же составом.
    initial.setDocumentGroups(groups.map((group) => ({ ...group })));

    expect(useReviewStore.getState().groupDecisions.G1).toBe("confirmed");
  });

  it("другой документ сбрасывает решения", () => {
    initial.setDocumentGroups(groupsOf());
    initial.confirmGroup("G1");
    initial.answerQuestion("TYPE-phone", "оставить");

    initial.setDocumentGroups([{ id: "X1", minConfidence: 1 }]);

    const state = useReviewStore.getState();
    expect(state.groupDecisions).toEqual({});
    expect(state.questionAnswers).toEqual({});
    expect(state.documentGroups).toHaveLength(1);
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
